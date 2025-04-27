import torch
import stopit
from time import time
from typing import List, Optional
from dataclasses import dataclass
from transformers.generation import LogitsProcessor

from core.utils import GENERATION_TIMEOUT
from core.registry import register_engine
from core.engine import Engine, EngineConfig
from core.types import (
    CompileStatus,
    CompileStatusCode,
    GenerationOutput,
    DecodingStatus,
    DecodingStatusCode,
)


class TimingLogitsProcessor(LogitsProcessor):
    """Logits processor that records timestamps for token generation."""

    def __init__(self):
        super().__init__()
        self.timestamps = []

    def __call__(self, _, scores):
        self.timestamps.append(time())
        return scores


@dataclass
class HuggingFaceConfig(EngineConfig):
    model: str
    temperature: float = 0
    max_tokens: Optional[int] = 4096


class HuggingFaceEngine(Engine[HuggingFaceConfig]):
    name = "huggingface"

    def __init__(self, config: HuggingFaceConfig):
        super().__init__(config)
        self.device = get_best_device()

        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(self.config.model)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.config.model, torch_dtype=torch.bfloat16
        ).to(self.device)
        self.tokenizer.pad_token = self.tokenizer.eos_token

    def _generate(self, output: GenerationOutput) -> None:
        from transformers.generation import GenerationConfig

        # strictly speaking, HuggingFace does not have a grammar compilation step
        output.metadata.grammar_compilation_end_time = time()
        output.metadata.compile_status = CompileStatus(code=CompileStatusCode.OK)

        timing_processor = TimingLogitsProcessor()
        generation_config = GenerationConfig(
            temperature=self.config.temperature,
            max_new_tokens=self.config.max_tokens,
        )

        input = self.tokenizer.apply_chat_template(
            output.messages, tokenize=False, add_generation_prompt=True
        )

        model_input = self.tokenizer(
            input,
            return_tensors="pt",
            add_special_tokens=False,
            padding=True,
            truncation=True,
        ).to(self.device)

        input_length = model_input["input_ids"].shape[1]

        try:
            with stopit.ThreadingTimeout(GENERATION_TIMEOUT) as to_ctx_mgr:
                if to_ctx_mgr.state == to_ctx_mgr.EXECUTING:
                    model_output = self.model.generate(
                        model_input["input_ids"],
                        generation_config=generation_config,
                        attention_mask=model_input["attention_mask"],
                        max_new_tokens=self.config.max_tokens,
                        logits_processor=[timing_processor],
                    )
                    output.metadata.decoding_status = DecodingStatus(
                        code=DecodingStatusCode.OK
                    )

            if len(timing_processor.timestamps) > 0:
                output.metadata.first_token_arrival_time = timing_processor.timestamps[
                    0
                ]

            if to_ctx_mgr.state == to_ctx_mgr.TIMED_OUT:
                output.metadata.decoding_status = DecodingStatus(
                    code=DecodingStatusCode.DECODING_TIMEOUT,
                    message="Generation timed out",
                )
                return

        except Exception as e:
            output.metadata.decoding_status = DecodingStatus(
                code=DecodingStatusCode.UNKOWN_ERROR, message=str(e)
            )
            return

        generated_sequences = model_output[:, input_length:]
        generated_texts = self.tokenizer.batch_decode(
            generated_sequences, skip_special_tokens=True
        )

        output_text = generated_texts[0] if generated_texts else ""

        if timing_processor.timestamps:
            output.metadata.first_token_arrival_time = timing_processor.timestamps[0]

        output.generation = extract_json_text_from_text(output_text)
        output.token_usage.output_tokens = self.count_tokens(output_text)

        return

    def encode(self, text: str) -> List[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def decode(self, ids: List[int]) -> str:
        return self.tokenizer.decode(ids, skip_special_tokens=True)

    @property
    def max_context_length(self) -> int:
        return self.tokenizer.model_max_length


def get_best_device():
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    else:
        return "cpu"


def extract_json_text_from_text(text: str) -> str:
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    else:
        return text.strip()


register_engine(HuggingFaceEngine, HuggingFaceConfig)
