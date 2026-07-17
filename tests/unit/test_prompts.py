from somai_chat.agent.prompts import RUNTIME_CAPABILITIES, SOMAI_IDENTITY, SOMAI_SYSTEM_PROMPT


def test_prompt_defines_somai_identity_and_tone() -> None:
    assert "运行于 SOMAI 系统中的通用具身智能助手" in SOMAI_IDENTITY
    assert "自然、沉稳、友好、简洁" in SOMAI_IDENTITY
    assert "不冒充真人" in SOMAI_IDENTITY


def test_prompt_requires_user_language_and_tts_friendly_output() -> None:
    assert "使用用户当前使用的语言" in SOMAI_IDENTITY
    assert "短句" in SOMAI_IDENTITY
    assert "口语化" in SOMAI_IDENTITY
    assert "TTS" in SOMAI_IDENTITY


def test_prompt_defines_embodied_and_safety_boundaries() -> None:
    assert "不要声称已经看见、感知或执行" in SOMAI_IDENTITY
    assert "说明当前能力边界" in SOMAI_IDENTITY
    assert "语言层面的帮助" in SOMAI_IDENTITY
    assert "一个关键澄清问题" in SOMAI_IDENTITY
    assert "危险或越权操作" in SOMAI_IDENTITY
    assert "安全替代" in SOMAI_IDENTITY


def test_prompt_separates_stable_identity_from_runtime_capabilities() -> None:
    assert "当前可用能力：文本多轮对话、当前天气查询" in RUNTIME_CAPABILITIES
    assert "未指定地点时默认查询武汉" in RUNTIME_CAPABILITIES
    assert "必须调用天气工具" in RUNTIME_CAPABILITIES
    assert "没有视觉、位置、设备状态或动作工具" in RUNTIME_CAPABILITIES
    assert SOMAI_SYSTEM_PROMPT == f"{SOMAI_IDENTITY}\n\n{RUNTIME_CAPABILITIES}"
    assert "{user" not in SOMAI_SYSTEM_PROMPT
