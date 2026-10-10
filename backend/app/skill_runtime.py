from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT_DIR / "skills"


def load_skill_prompt(skill_name: str, *, references: tuple[str, ...] = ()) -> str:
    """Load the instructions that the application model must follow at runtime."""
    skill_dir = SKILLS_DIR / skill_name
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.is_file():
        raise RuntimeError(f"Skill 不存在: {skill_name}")

    parts = [f"# Runtime Skill: {skill_name}\n", skill_path.read_text(encoding="utf-8")]
    for relative_path in references:
        reference_path = skill_dir / relative_path
        if not reference_path.is_file():
            raise RuntimeError(f"Skill reference 不存在: {skill_name}/{relative_path}")
        parts.extend(
            [
                f"\n# Skill Reference: {relative_path}\n",
                reference_path.read_text(encoding="utf-8"),
            ]
        )
    return "\n".join(parts)
