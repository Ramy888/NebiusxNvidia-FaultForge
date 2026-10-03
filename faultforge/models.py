from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    fault: str
    test_code: str

    @property
    def test_path(self) -> str:
        return f"tests/test_ff_{self.id}.py"


@dataclass(frozen=True)
class Candidate:
    id: str
    summary: str
    files: dict[str, str] = field(default_factory=dict)
