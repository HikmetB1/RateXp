"""Open the chat model a seeded run thinks with, from config.yaml's ``model`` id.

An ``azure_openai:`` model reads AZURE_OPENAI_ENDPOINT and OPENAI_API_VERSION from
the environment (Terraform sets both on the Function App) and, with no API key set,
authenticates passwordlessly: an Entra token from the host's Managed Identity, or
locally your own ``az login``. That is how the deployed function reaches AI Foundry -
its identity holds "Cognitive Services OpenAI User" on the account and no key exists
anywhere. A plain ``openai:`` model, or an explicit AZURE_OPENAI_API_KEY, takes its
usual path.

The framework and model names live here too, because this is the file that decides
what they are; both end up stamped on every record core stores.
"""

from __future__ import annotations

import os

from langchain.chat_models import init_chat_model
from load_config import MODEL, TEMPERATURE

# The agent framework driving every seeded run, recorded as the ATIF agent name.
FRAMEWORK = "langchain"


def model_name() -> str:
    """The bare model or deployment name, without init_chat_model's provider prefix."""
    return MODEL.split(":")[-1]


def open_chat_model():
    """Build the configured chat model. Holds no resources - there is nothing to close."""
    kwargs = {"temperature": TEMPERATURE}
    if MODEL.startswith("azure_openai:") and not os.environ.get("AZURE_OPENAI_API_KEY"):
        # Imported here so an openai: model never has to load the Azure identity stack.
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
    return init_chat_model(MODEL, **kwargs)
