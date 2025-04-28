from .engine import Engine
from pse.structuring_engine import StructuringEngine


class PSEEngine(Engine):
    def __init__(self):
        super().__init__()

    def init(self):
        self.pse = StructuringEngine(self.tokenizer)
        self.vocab_size = self.tokenizer.vocab_size

    def get_id(self):
        return "pse"

    def get_name(self):
        return "Proxy Structuring Engine"

    def get_module(self):
        return "pse"

    def compile_grammar(self, schema: dict):
        self.pse.configure(schema)

    def reset(self):
        self.pse.reset()

    def compute_mask(self):
        return self.pse.compute_token_mask(self.vocab_size)

    def commit_token(self, t: int) -> bool:
        self.pse.consume(t, token_healing=False)
        result = len(self.pse.steppers) > 0
        return result
