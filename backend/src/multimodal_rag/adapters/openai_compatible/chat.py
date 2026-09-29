"""Answer body of the ``chat/completions`` route of the OpenAI API format.

Every client of that route reads the same part of the answer, the text of the first
generated message, so the model of that body is shared.
"""

import pydantic


class _Message(pydantic.BaseModel):
    content: str | None = None


class _Choice(pydantic.BaseModel):
    message: _Message
    finish_reason: str | None = None


class ChatCompletion(pydantic.BaseModel):
    """Part of a ``chat/completions`` answer that the clients read.

    Attributes:
        choices: Generated messages, at least one.
    """

    choices: list[_Choice] = pydantic.Field(min_length=1)

    @property
    def content(self) -> str:
        """Text of the first generated message, empty when it has none."""
        return self.choices[0].message.content or ""

    @property
    def reached_token_limit(self) -> bool:
        """Whether the first message was cut by the ``max_tokens`` limit."""
        return self.choices[0].finish_reason == "length"
