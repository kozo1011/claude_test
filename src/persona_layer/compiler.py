"""ペルソナ定義から LLM 用プロンプトを決定的に生成するコンパイラ。

生成されるシステムプロンプトが「移植可能な人格」の実行形式であり、
どの LLM エージェントに渡しても同じ人格として振る舞うことを狙う。
テンプレートはペルソナの ``language`` に応じて日本語/英語を切り替える。
"""

from __future__ import annotations

from .schema import Formality, Persona, ResponseLength

_LENGTH_JA = {
    ResponseLength.short: "簡潔に、要点のみ答える",
    ResponseLength.medium: "適度な長さで答える",
    ResponseLength.long: "丁寧に、十分な説明を添えて答える",
}
_FORMALITY_JA = {
    Formality.casual: "くだけた話し方",
    Formality.polite: "丁寧語（です・ます調）",
    Formality.formal: "改まった敬語",
}
_LENGTH_EN = {
    ResponseLength.short: "Keep responses short and to the point",
    ResponseLength.medium: "Keep responses moderately sized",
    ResponseLength.long: "Give thorough, well-explained responses",
}
_FORMALITY_EN = {
    Formality.casual: "casual",
    Formality.polite: "polite",
    Formality.formal: "formal",
}


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items if item]


def compile_system_prompt(persona: Persona, include_examples: bool = True) -> str:
    """ペルソナをシステムプロンプト（テキスト）に変換する。"""
    if persona.language.split("-")[0].lower() == "ja":
        return _compile_ja(persona, include_examples)
    return _compile_en(persona, include_examples)


def _compile_ja(p: Persona, include_examples: bool) -> str:
    sections: list[str] = []

    header = [f"あなたは「{p.name}」です。"]
    if p.description:
        header.append(p.description)
    sections.append("\n".join(header))

    identity: list[str] = []
    if p.identity.role:
        identity.append(f"- 役割: {p.identity.role}")
    if p.identity.background:
        identity.append(f"- 背景: {p.identity.background}")
    if p.identity.first_person:
        identity.append(f"- 一人称: {p.identity.first_person}")
    if p.identity.audience:
        identity.append(f"- 対話相手: {p.identity.audience}")
    if identity:
        sections.append("## あなたのプロフィール\n" + "\n".join(identity))

    personality: list[str] = []
    if p.personality.traits:
        personality.append(f"- 性格: {'、'.join(p.personality.traits)}")
    if p.personality.tone:
        personality.append(f"- 口調: {p.personality.tone}")
    personality.append(f"- 言葉遣い: {_FORMALITY_JA[p.personality.formality]}")
    if p.personality.humor:
        personality.append(f"- ユーモア: {p.personality.humor}")
    sections.append("## 人格\n" + "\n".join(personality))

    style: list[str] = []
    if p.speech_style.sentence_endings:
        style.append(f"- よく使う語尾: {'、'.join(p.speech_style.sentence_endings)}")
    if p.speech_style.favorite_phrases:
        style.append(f"- 口癖: {'、'.join(p.speech_style.favorite_phrases)}")
    if p.speech_style.avoid_words:
        style.append(f"- 使わない言葉: {'、'.join(p.speech_style.avoid_words)}")
    style.extend(_bullets(p.speech_style.quirks))
    style.append(f"- {_LENGTH_JA[p.speech_style.response_length]}")
    if p.speech_style.formatting.value == "plain":
        style.append("- 音声で読み上げられる場合があるため、記号や箇条書きに頼らず自然な文章で話す")
    if style:
        sections.append("## 話し方\n" + "\n".join(style))

    behavior: list[str] = []
    behavior.extend(_bullets([f"目的: {g}" for g in p.behavior.goals]))
    behavior.extend(_bullets(p.behavior.guidelines))
    if p.behavior.on_unknown:
        behavior.append(f"- {p.behavior.on_unknown}")
    if behavior:
        sections.append("## 行動指針\n" + "\n".join(behavior))

    knowledge: list[str] = []
    if p.knowledge.domains:
        knowledge.append(f"- 得意分野: {'、'.join(p.knowledge.domains)}")
    knowledge.extend(_bullets(p.knowledge.facts))
    if knowledge:
        sections.append("## 知識・設定\n" + "\n".join(knowledge))

    prohibited = _bullets(p.behavior.prohibited + p.safety.restrictions)
    if p.safety.ai_disclosure:
        prohibited.append("- AIかどうかを尋ねられたら、正直にAIであると認める")
    if prohibited:
        sections.append("## してはいけないこと\n" + "\n".join(prohibited))

    if include_examples and p.examples:
        lines = ["## 応答例"]
        for ex in p.examples:
            lines.append(f"相手: {ex.user}")
            lines.append(f"あなた: {ex.assistant}")
            lines.append("")
        sections.append("\n".join(lines).rstrip())

    sections.append("以上の人格・話し方を、会話が長くなっても一貫して保ってください。")
    return "\n\n".join(sections)


def _compile_en(p: Persona, include_examples: bool) -> str:
    sections: list[str] = []

    header = [f'You are "{p.name}".']
    if p.description:
        header.append(p.description)
    sections.append("\n".join(header))

    identity: list[str] = []
    if p.identity.role:
        identity.append(f"- Role: {p.identity.role}")
    if p.identity.background:
        identity.append(f"- Background: {p.identity.background}")
    if p.identity.audience:
        identity.append(f"- Audience: {p.identity.audience}")
    if identity:
        sections.append("## Profile\n" + "\n".join(identity))

    personality: list[str] = []
    if p.personality.traits:
        personality.append(f"- Traits: {', '.join(p.personality.traits)}")
    if p.personality.tone:
        personality.append(f"- Tone: {p.personality.tone}")
    personality.append(f"- Register: {_FORMALITY_EN[p.personality.formality]}")
    if p.personality.humor:
        personality.append(f"- Humor: {p.personality.humor}")
    sections.append("## Personality\n" + "\n".join(personality))

    style: list[str] = []
    if p.speech_style.favorite_phrases:
        style.append(f"- Signature phrases: {', '.join(p.speech_style.favorite_phrases)}")
    if p.speech_style.avoid_words:
        style.append(f"- Never say: {', '.join(p.speech_style.avoid_words)}")
    style.extend(_bullets(p.speech_style.quirks))
    style.append(f"- {_LENGTH_EN[p.speech_style.response_length]}")
    if p.speech_style.formatting.value == "plain":
        style.append(
            "- Responses may be read aloud; speak in natural sentences without relying on symbols or bullet lists"
        )
    sections.append("## Speaking style\n" + "\n".join(style))

    behavior: list[str] = []
    behavior.extend(_bullets([f"Goal: {g}" for g in p.behavior.goals]))
    behavior.extend(_bullets(p.behavior.guidelines))
    if p.behavior.on_unknown:
        behavior.append(f"- {p.behavior.on_unknown}")
    if behavior:
        sections.append("## Behavior\n" + "\n".join(behavior))

    knowledge: list[str] = []
    if p.knowledge.domains:
        knowledge.append(f"- Expertise: {', '.join(p.knowledge.domains)}")
    knowledge.extend(_bullets(p.knowledge.facts))
    if knowledge:
        sections.append("## Knowledge\n" + "\n".join(knowledge))

    prohibited = _bullets(p.behavior.prohibited + p.safety.restrictions)
    if p.safety.ai_disclosure:
        prohibited.append("- If asked whether you are an AI, honestly acknowledge it")
    if prohibited:
        sections.append("## Never do\n" + "\n".join(prohibited))

    if include_examples and p.examples:
        lines = ["## Example exchanges"]
        for ex in p.examples:
            lines.append(f"User: {ex.user}")
            lines.append(f"You: {ex.assistant}")
            lines.append("")
        sections.append("\n".join(lines).rstrip())

    sections.append("Stay consistently in this persona throughout the conversation.")
    return "\n\n".join(sections)


def compile_style_prompt(persona: Persona) -> str:
    """中継モード用: 上流エージェントの応答内容を、意味を変えずに
    このペルソナの話し方へ書き換えるための指示プロンプトを生成する。
    """
    base = compile_system_prompt(persona, include_examples=True)
    if persona.language.split("-")[0].lower() == "ja":
        task = (
            "これから渡すテキストの内容・事実関係は一切変えずに、"
            "上記の人格の話し方に書き換えてください。"
            "情報の追加・削除はせず、書き換えた本文のみを出力してください。"
        )
    else:
        task = (
            "Rewrite the text you are given into the persona's voice described above. "
            "Do not add, remove, or alter any information. Output only the rewritten text."
        )
    return base + "\n\n" + task
