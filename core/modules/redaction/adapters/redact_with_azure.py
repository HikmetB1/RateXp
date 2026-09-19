"""Azure AI Language PII redaction adapter (billed per 1,000 text records).

Sends each text to Azure's ``recognize_pii_entities`` and returns the masked
text. Authenticates with the Managed Identity (azure-identity) - no key stored.
Per-message language is auto-detected; a document the model rejects is retried
once in the fallback language (the first configured one). Install the
``redaction-azure`` extra.
"""

from __future__ import annotations


class AzureRedactor:
    # Azure AI Language accepts at most 5 documents per PII request.
    _BATCH = 5

    def __init__(self, *, endpoint: str, languages: list[str]) -> None:
        if not endpoint:
            raise RuntimeError(
                "redaction.provider is 'azure' but redaction.azure_endpoint is empty in config.yaml"
            )
        self._endpoint = endpoint
        self._fallback = languages[0]
        # Detected ISO 639-1 code (e.g. "zh") -> the configured PII code (e.g. "zh-hans").
        self._lang_by_iso = {code.split("-", 1)[0].lower(): code for code in languages}
        self._client = None  # built lazily so importing this module needs no SDK

    def _get_client(self):
        if self._client is None:
            from azure.ai.textanalytics import TextAnalyticsClient
            from azure.identity import DefaultAzureCredential

            self._client = TextAnalyticsClient(self._endpoint, DefaultAzureCredential())
        return self._client

    def _detect_languages(self, texts: list[str]) -> list[str]:
        """Pick a PII language per document: the auto-detected one if configured,
        else the fallback (first configured language)."""
        langs: list[str] = []
        for doc in self._get_client().detect_language(texts):
            iso = "" if doc.is_error else (doc.primary_language.iso6391_name or "").lower()
            langs.append(self._lang_by_iso.get(iso, self._fallback))
        return langs

    def _redact_batch(self, texts: list[str]) -> list[str]:
        client = self._get_client()
        langs = self._detect_languages(texts)
        docs = [{"id": str(i), "text": t, "language": langs[i]} for i, t in enumerate(texts)]
        out: list[str] = [""] * len(texts)
        retry: list[int] = []
        for doc in client.recognize_pii_entities(docs):
            i = int(doc.id)
            if doc.is_error:
                retry.append(i)  # detected language may be unsupported - try the fallback
            else:
                out[i] = doc.redacted_text
        if retry:
            rdocs = [{"id": str(i), "text": texts[i], "language": self._fallback} for i in retry]
            for doc in client.recognize_pii_entities(rdocs):
                if doc.is_error:
                    raise RuntimeError(f"Azure PII redaction failed: {doc.error}")
                out[int(doc.id)] = doc.redacted_text
        return out

    def redact_texts(self, texts: list[str]) -> list[str]:
        out: list[str] = []
        for start in range(0, len(texts), self._BATCH):
            out.extend(self._redact_batch(texts[start : start + self._BATCH]))
        return out
