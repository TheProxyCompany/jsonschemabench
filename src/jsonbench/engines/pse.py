from time import time
from typing import List, Optional
from dataclasses import dataclass

from core.registry import register_engine
from core.engine import Engine, EngineConfig
from core.types import (
    CompileStatus,
    DecodingStatus,
    GenerationOutput,
    CompileStatusCode,
    DecodingStatusCode,
    Token,
)

from proxy_inference_engine.engine import InferenceEngine, GenerationRequest


@dataclass
class PSEConfig(EngineConfig):
    model: str
    temperature: float = 0.2
    max_tokens: Optional[int] = None

class PSEEngine(Engine[PSEConfig]):
    name = "proxy-structuring-engine"

    def __init__(self, config: PSEConfig):
        super().__init__(config)

        self.engine = InferenceEngine(self.config.model)
        self.tokenizer = self.engine.tokenizer._tokenizer

    def _generate(self, output: GenerationOutput) -> None:

        self.engine.structuring_engine.configure(output.schema)
        output.metadata.grammar_compilation_end_time = time()
        output.metadata.compile_status = CompileStatus(code=CompileStatusCode.OK)

        generation_request = GenerationRequest(prompt=output.messages)
        tokenizer_config = {
            "prompt": generation_request.prompt,
            **self.engine.tokenizer.control_tokens.model_dump(),
        }
        encoded_prompt = self.engine.tokenizer.encode(**tokenizer_config)
        self.engine.logits_processors["root"] = self.engine.make_processors()
        self.engine.samplers["root"] = self.engine.make_sampler(
            temperature=self.config.temperature,
        )

        generated_tokens = []
        for token, _ in self.engine.generate(
            encoded_prompt,
            max_completion_tokens=self.config.max_tokens
        ):
            if not generated_tokens:
                output.metadata.first_token_arrival_time = time()

            generated_tokens.append(token)

        output.token_usage.output_tokens = len(generated_tokens)
        output.generated_tokens = [Token(id=token_id) for token_id in generated_tokens]
        output.generation = self.engine.tokenizer.decode(generated_tokens)
        output.metadata.decoding_status = DecodingStatus(code=DecodingStatusCode.OK)

    def encode(self, text: str) -> Optional[List[int]]:
        return self.tokenizer.encode(text)

    def decode(self, ids: List[int]) -> Optional[str]:
        return self.tokenizer.decode(ids)

    @property
    def max_context_length(self) -> int:
        return 4096

    def close(self):
        pass


register_engine(PSEEngine, PSEConfig)
