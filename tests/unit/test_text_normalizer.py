from somai_chat.application.text_normalizer import TextNormalizer


def test_normalizer_removes_markdown_and_expands_common_tts_units() -> None:
    normalizer = TextNormalizer()

    text = normalizer.normalize(
        "## 武汉天气\n\n气温 **34°C**，风速 `26 km/h`。\n- 多喝水"
    )

    assert text == "武汉天气\n\n气温 34 摄氏度，风速 26 千米每小时。\n多喝水"


def test_normalizer_handles_formatting_tokens_split_across_stream_chunks() -> None:
    normalizer = TextNormalizer()

    chunks = [normalizer.normalize_delta(part) for part in ("气温 *", "*34°C", "**")]

    assert "".join(chunks) == "气温 34 摄氏度"


def test_normalizer_removes_markdown_destinations_and_bare_urls() -> None:
    normalizer = TextNormalizer()

    text = normalizer.normalize(
        "详情见 [新华网](https://news.example/a) 或 https://example.com/x，也可访问 www.example.org。"
    )

    assert "新华网" in text
    assert "https://" not in text
    assert "www." not in text
