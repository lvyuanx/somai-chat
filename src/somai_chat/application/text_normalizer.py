"""Normalize model text for direct text-to-speech playback."""

import re


class TextNormalizer:
    """Remove presentation markup and expand common weather units."""

    _markdown_link = re.compile(r"\[([^\]]+)\]\([^)]*\)")
    _bare_url = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>，。！？；：、]+")
    _heading = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
    _list_marker = re.compile(r"(?m)^\s*(?:[-+*]|\d+[.)])\s+")
    _celsius = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:°\s*)?[Cc]\b")
    _kilometers_per_hour = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*km\s*/\s*h\b", re.IGNORECASE)

    def normalize(self, text: str) -> str:
        """Return plain, speakable text without Markdown presentation tokens."""
        plain_text = self._markdown_link.sub(r"\1", text)
        plain_text = self._bare_url.sub("", plain_text)
        plain_text = self._heading.sub("", plain_text)
        plain_text = self._list_marker.sub("", plain_text)
        plain_text = plain_text.replace("**", "").replace("__", "").replace("`", "")
        plain_text = plain_text.replace("*", "")
        plain_text = self._celsius.sub(r"\g<value> 摄氏度", plain_text)
        return self._kilometers_per_hour.sub(r"\g<value> 千米每小时", plain_text)

    def normalize_delta(self, text: str) -> str:
        """Normalize an independent streaming text delta."""
        return self.normalize(text)
