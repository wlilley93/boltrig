"""Nothing a caller sends can become a FLAG in the trainer's argv (DIS-4).

CodeQL flags both ``subprocess.run`` calls in the sidecar as
``py/command-line-injection`` (alerts 34 and 35, critical). Neither is
exploitable: the calls pass a list with no shell, and every caller-supplied
value that reaches argv is first put through ``_MODEL_NAME_RE``, which is
anchored and begins with ``[A-Za-z0-9]`` -- so a value can never read as a
flag. But "I read the regex and it looked anchored" is not a control, and the
alerts were dismissed on the strength of this file rather than on that reading.

What is actually at stake is one of the sidecar's two load-bearing clauses:

    training always starts from the bare base model. There is no field, path
    or flag through which a prior adapter can seed a run.

mlx_lm.lora HAS a ``--resume-adapter-file``. If a crafted ``model`` or
``base_pin`` could reach argv unaltered, that flag becomes reachable from the
network and the clause is false. So the test worth having is not "the regex is
unchanged" but "the guard still refuses flag-shaped input, and the flag is
still absent from every argv this module composes".
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SIDECAR = (Path(__file__).resolve().parents[2]
           / "services" / "distill_sidecar" / "app.py")


def _load() -> ModuleType:
    """Import by path: the sidecar is a service, not part of the boltrig
    package, and it deliberately has no import-time side effects (constants and
    a ``__main__``-guarded ``main``), so loading it here starts nothing."""
    spec = importlib.util.spec_from_file_location("distill_sidecar_app", SIDECAR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = _load()


# Flag-shaped first, because that is the class the alert is about; the shell
# metacharacters are here to record that they are irrelevant (no shell is
# involved) rather than to suggest they are the danger.
REFUSED = [
    "--resume-adapter-file=/tmp/evil",   # the exact flag DIS-4 forbids
    "--resume-adapter-file",
    "-c",
    "--model",
    "--data=/etc",
    "-",
    "; rm -rf /",
    "$(id)",
    "`id`",
    "a; id",
    "a b",
    "a\nb",
    "a\x00b",
    "../../etc/passwd",
    "mlx-community/../../etc",
    "",
]

ACCEPTED = [
    "mlx-community/Qwen2.5-7B-Instruct-4bit",
    "meta-llama/Llama-3.1-8B@main",
    "Qwen3-8B-4bit",
]


@pytest.mark.parametrize("payload", REFUSED)
def test_model_argument_refuses_anything_flag_shaped(payload: str) -> None:
    """The guard itself, and then the call site's message.

    Asserting only ``pytest.raises(ValueError)`` here was VACUOUS, and mutation
    testing caught it: ``_model_args`` also calls ``load_corpus``, which raises
    ValueError for a bad digest, so the assertion was satisfied by the digest
    check no matter what the model check did. Loosening the regex to
    ``^[A-Za-z0-9-]`` -- which makes ``--resume-adapter-file`` an accepted model
    name -- left all twenty-one tests green. Match on the message, so the
    exception has to be the one this test is about.
    """
    assert not (app._MODEL_NAME_RE.fullmatch(payload) and ".." not in payload), (
        f"{payload!r} passes the shape check and can reach argv as a flag")
    with pytest.raises(ValueError, match="refused model name"):
        app._model_args("", payload)


@pytest.mark.parametrize("payload", ACCEPTED)
def test_real_repo_names_still_pass_the_shape_check(payload: str) -> None:
    assert app._MODEL_NAME_RE.fullmatch(payload), (
        f"{payload!r} is a legitimate model repo and must not be refused")


def test_no_subprocess_call_uses_a_shell() -> None:
    """A list argv is why the shell metacharacters above are inert. If any call
    grows ``shell=True`` they stop being inert, and the alerts stop being
    false."""
    tree = ast.parse(SIDECAR.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "run"
             and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "subprocess"]
    assert calls, "expected the sidecar to still shell out to mlx"
    for call in calls:
        shell = next((k for k in call.keywords if k.arg == "shell"), None)
        assert shell is None, f"subprocess.run(shell=...) at line {call.lineno}"
        assert isinstance(call.args[0], (ast.Name, ast.List)), (
            f"argv at line {call.lineno} is not a list built in this module")


def test_the_forbidden_resume_flag_appears_nowhere() -> None:
    """DIS-4's clause, as a fact about the file rather than a promise in its
    docstring. The comment naming the flag is allowed; a string that could
    reach argv is not."""
    tree = ast.parse(SIDECAR.read_text(encoding="utf-8"))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    offenders = [s for s in literals if "resume-adapter-file" in s
                 and not s.lstrip().startswith(("mlx's", "The", "Two"))
                 and "\n" not in s]
    assert not offenders, (
        f"a resume-adapter string is reachable as a value: {offenders}")
