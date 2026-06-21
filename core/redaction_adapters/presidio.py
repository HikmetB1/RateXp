"""Presidio PII redaction adapter (self-hosted, no per-call cost).

Detects each message's language and masks PII with Presidio plus a per-language
spaCy small model. spaCy only ships NER pipelines for some languages, so this
covers the configured languages it supports (see _SPACY_MODELS) and falls back to
the first of those for anything else. Structured PII (emails, phones, cards) is
still masked for every language via an English pattern pass. Install the
`redaction-presidio` extra; the Dockerfile downloads the spaCy models.
"""

from __future__ import annotations

# Configured BCP-47 base code -> the spaCy small model that handles it. Only
# languages whose spaCy models need no extra native tokenizer are included here.
# Others (zh needs a segmenter; ar/hi/bn/ur have no spaCy NER model at all) aren't
# covered for names, though pattern PII (email/phone/card) is still masked for them.
_SPACY_MODELS = {
    "en": "en_core_web_sm",
    "es": "es_core_news_sm",
    "fr": "fr_core_news_sm",
    "pt": "pt_core_news_sm",
    "ru": "ru_core_news_sm",
}


class PresidioRedactor:
    def __init__(self, *, languages: list[str]) -> None:
        # Keep the configured languages spaCy can model, in order (deduped).
        codes: list[str] = []
        for lang in languages:
            base = lang.split("-", 1)[0].lower()
            if base in _SPACY_MODELS and base not in codes:
                codes.append(base)
        self._supported = codes or ["en"]
        self._fallback = self._supported[0]

        import langdetect
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        langdetect.DetectorFactory.seed = 0  # deterministic detection
        self._detect = langdetect.detect

        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": c, "model_name": _SPACY_MODELS[c]} for c in self._supported
                ],
            }
        ).create_engine()
        self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=self._supported)
        self._anonymizer = AnonymizerEngine()

    def _language_of(self, text: str) -> str:
        """Detect the text's language, mapped to a supported spaCy code (else fallback)."""
        try:
            base = self._detect(text).split("-", 1)[0].lower()
        except Exception:  # noqa: BLE001 - langdetect raises on featureless text
            return self._fallback
        return base if base in self._supported else self._fallback

    def redact_texts(self, texts: list[str]) -> list[str]:
        out: list[str] = []
        for text in texts:
            lang = self._language_of(text)
            results = self._analyzer.analyze(text=text, language=lang)
            if lang != "en" and "en" in self._supported:
                # Pattern recognizers (email/phone/card) are English-tagged in Presidio;
                # an extra English pass catches that structured PII for any language.
                results = results + self._analyzer.analyze(text=text, language="en")
            out.append(self._anonymizer.anonymize(text=text, analyzer_results=results).text)
        return out
