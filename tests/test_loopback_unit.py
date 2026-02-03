from loopback.loopback import LoopbackConfig, ToolImage, ToolResult, should_loopback


def test_should_loopback_respects_marker_and_gates():
    config = LoopbackConfig(enabled=True)
    tool_result = ToolResult(
        tool_name="generate_image",
        images=[ToolImage(mime_type="image/png", data=b"123")],
    )

    decision = should_loopback(config, tool_result, already_looped=False, model_supports_vision=True)
    assert decision.should_loopback is True

    decision = should_loopback(config, tool_result, already_looped=True, model_supports_vision=True)
    assert decision.should_loopback is False
    assert decision.reason == "loopback already performed"

    decision = should_loopback(config, tool_result, already_looped=False, model_supports_vision=False)
    assert decision.should_loopback is False
    assert decision.reason == "model lacks vision support"
