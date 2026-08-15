from boltrig.kernel.run_event_projection import _event_safe


def test_media_payload_bytes_never_enter_the_run_event_relay():
    projected = _event_safe(
        {
            "id": "frame_1",
            "media_type": "image/jpeg",
            "data": "base64-browser-frame",
            "nested": {"title": "safe"},
        }
    )

    assert projected == {
        "id": "frame_1",
        "media_type": "image/jpeg",
        "data": "[redacted]",
        "nested": {"title": "safe"},
    }


def test_non_media_data_remains_available_to_existing_tool_events():
    assert _event_safe({"media_type": "text/plain", "data": "hello"})["data"] == "hello"
