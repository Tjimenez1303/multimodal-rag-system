"""``FigureDescriber`` over the ``chat/completions`` route of the OpenAI API format.

The figure travels as a base64 PNG data URI in an ``image_url`` part. Thinking is
disabled per request with ``chat_template_kwargs``, a llama.cpp extension to the
format, as a second guard next to the server's runtime flag.
"""

import asyncio
import base64
import io

import httpx
import pydantic
from PIL import Image, UnidentifiedImageError

from multimodal_rag.adapters.openai_compatible.transport import post_json
from multimodal_rag.shared.errors import DataInconsistencyError, ProviderResponseError
from multimodal_rag.shared.resilience import RetryPolicy

SERVICE = "vision model"
# Longest side sent to the model, which bounds the cost of each description.
MAX_IMAGE_SIDE = 1280
MAX_DESCRIPTION_TOKENS = 512
# Instructions come first and the manual's text is fenced below them, so that text is
# never read as an instruction. The language rule is repeated after the fenced text,
# because a small model answering an English prompt otherwise keeps writing English.
PROMPT = """You describe figures from technical manuals so they can be found by search.
Write two to four sentences that describe what the figure shows, using only what is
visible in it. Then write a line that starts with "Labels:" and lists every label,
code and number printed in the figure, verbatim and separated by commas.
Write in the language of the caption and surrounding text below, or in English when
both are (none).

Caption:
<<<
{caption}
>>>

Surrounding text:
<<<
{context}
>>>

Language: write the whole answer, including the "Labels:" line, in the same language
as the caption and surrounding text above. If that text is Spanish, answer in Spanish.
If both are (none), answer in English."""


class _Message(pydantic.BaseModel):
    content: str | None = None


class _Choice(pydantic.BaseModel):
    message: _Message


class ChatCompletion(pydantic.BaseModel):
    """Part of a ``chat/completions`` answer that the describer reads.

    Attributes:
        choices: Generated messages, at least one.
    """

    choices: list[_Choice] = pydantic.Field(min_length=1)


class OpenAICompatibleFigureDescriber:
    """Describes figures with a vision model served in the OpenAI API format.

    Args:
        client: Client configured with the server's base URL and timeout.
        model: Model reference, such as ``ai/qwen3.5:9b``.
        retry: Retry policy for transient failures.
    """

    def __init__(
        self, client: httpx.AsyncClient, *, model: str, retry: RetryPolicy
    ) -> None:
        self._client = client
        self._model = model
        self._retry = retry

    async def describe(
        self, *, image_png: bytes, caption: str | None, context: str | None
    ) -> str:
        """Return a short description of a figure plus its printed labels.

        Args:
            image_png: The figure as PNG bytes.
            caption: Caption of the figure, if any.
            context: Text surrounding the figure, if any.

        Returns:
            The description, written in the language of the caption and context, or
            in English when both are missing.

        Raises:
            ProviderUnavailableError: If the model stays unreachable after retries.
            ProviderTimeoutError: If the model keeps timing out after retries.
            ProviderResponseError: If the model rejects the request or answers
                without text.
            DataInconsistencyError: If the stored crop is not a readable image.
        """
        image = await asyncio.to_thread(_downscaled_png, image_png)
        prompt = PROMPT.format(caption=caption or "(none)", context=context or "(none)")
        encoded = base64.b64encode(image).decode()
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": MAX_DESCRIPTION_TOKENS,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        completion = await post_json(
            self._client,
            "chat/completions",
            payload,
            answer=ChatCompletion,
            service=SERVICE,
            retry=self._retry,
        )
        content = (completion.choices[0].message.content or "").strip()
        if not content:
            raise ProviderResponseError(f"The {SERVICE} answered an empty description")
        return content


def _downscaled_png(image_png: bytes) -> bytes:
    try:
        image = Image.open(io.BytesIO(image_png))
        image.load()
    except UnidentifiedImageError as error:
        raise DataInconsistencyError("A stored figure crop is not an image") from error
    if max(image.size) <= MAX_IMAGE_SIDE:
        return image_png
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
