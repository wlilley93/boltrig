from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PANELS = ROOT / "ui" / "src" / "panels"


@pytest.mark.invariant("SEC-75")
def test_high_control_mutations_render_the_pending_human_contract() -> None:
    callsites = {
        "studio/skillsStudio/SkillUpsertForm.tsx": ("control.skill.upsert",),
        "studio/RouterStudio.tsx": (
            "control.noun.define",
            "control.verb.define",
            "control.binding.set",
        ),
        "studio/AdapterStudio.tsx": ("control.adapter.activate",),
        "studio/workflow/forms/ScheduleForm.tsx": (
            "control.workflow.schedule",
        ),
        "studio/workflow/forms/TriggerForm.tsx": ("control.workflow.trigger",),
        "admin/AdminConfigView.tsx": ("pending.verb",),
        "admin/tenancy/UserDirectory.tsx": (
            "control.user.update",
            "control.user.deactivate",
        ),
    }
    for relative, verbs in callsites.items():
        source = (PANELS / relative).read_text(encoding="utf-8")
        assert "PendingHumanCard" in source, relative
        for verb in verbs:
            assert verb in source, f"{relative} does not surface {verb} pending state"

    # The named files above are read individually, so a wholesale-missing panels
    # tree errors before here - but a PARTIAL move (panels relocated while those
    # few stay) leaves this glob short and the bypass ratchet below vacuous, since
    # no source means no forbidden call found.
    panel_files = list(PANELS.rglob("*.ts*"))
    assert len(panel_files) >= len(callsites), (
        f"scanned nothing meaningful: {PANELS} yielded {len(panel_files)} files for "
        f"{len(callsites)} named callsites - the bypass check below would pass empty"
    )
    panel_source = "\n".join(
        path.read_text(encoding="utf-8") for path in panel_files
    )
    bypass_calls = (
        "api.upsertSkill(",
        "api.upsertNoun(",
        "api.upsertVerb(",
        "api.setBinding(",
        "api.activateAdapter(",
        "api.scheduleWorkflow(",
        "api.triggerWorkflow(",
        "api.configRollback(",
        "api.patchUser(",
    )
    for call in bypass_calls:
        assert call not in panel_source, f"high mutation bypasses governed UI: {call}"
