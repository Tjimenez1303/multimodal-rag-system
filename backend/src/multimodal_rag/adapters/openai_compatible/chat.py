"""Answer body of the ``chat/completions`` route of the OpenAI API format.

Every client of that route reads the same part of the answer, the first generated
message, so the model of that body is shared. The reranker also reads the log
probabilities of the first generated token, which the route returns when a request
sets ``logprobs`` and ``top_logprobs``.
"""

import pydantic


class _Message(pydantic.BaseModel):
    content: str | None = None


class _TopLogprob(pydantic.BaseModel):
    token: str
    logprob: float


class _TokenLogprob(pydantic.BaseModel):
    top_logprobs: list[_TopLogprob] = pydantic.Field(default_factory=list)


class _Logprobs(pydantic.BaseModel):
    content: list[_TokenLogprob] | None = None


class _Choice(pydantic.BaseModel):
    message: _Message
    finish_reason: str | None = None
    logprobs: _Logprobs | None = None


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

    @property
    def first_token_logprobs(self) -> dict[str, float] | None:
        """Log probability of each candidate for the first generated token.

        Returns:
            The candidates the server listed, by token text, or ``None`` when the
            answer carries no log probabilities.
        """
        logprobs = self.choices[0].logprobs
        if logprobs is None or not logprobs.content:
            return None
        return {top.token: top.logprob for top in logprobs.content[0].top_logprobs}
