"""Sample DM threads used in demo mode (no Instagram connection required)."""

from datetime import datetime, timedelta, timezone

from .models import Message, Thread

_THREADS = [
    ("priya_builds", [
        (6.5, False, "Loved the video on RAG pipelines! Could you do one on how to evaluate RAG quality in production?"),
        (6.4, True, "Thanks Priya! Noted."),
        (2.1, False, "Also - how do you decide between fine-tuning and just better prompting? Would be a great video"),
    ]),
    ("marcus.cto", [
        (5.8, False, "Hey, any chance you could cover how to pitch an AI budget to a non-technical board? My CFO keeps asking for ROI numbers."),
    ]),
    ("devops_dana", [
        (5.2, False, "Great content. Suggestion: a video on evaluating RAG systems - metrics, test sets, all that. Nobody explains it well."),
        (0.9, False, "🔥🔥🔥"),
    ]),
    ("startup_sam", [
        (4.9, False, "When should a startup fine tune a model vs prompt engineering? Confused about cost tradeoffs"),
        (4.7, False, "also what's your take on agents frameworks like LangGraph vs rolling your own?"),
    ]),
    ("lena_product", [
        (4.1, False, "Would love a breakdown of how product managers should write specs for AI features. Nobody knows how to spec non-deterministic stuff."),
    ]),
    ("theo_engineer", [
        (3.6, False, "Can you explain how to measure whether a RAG chatbot is actually giving correct answers? We have no idea if ours is good."),
        (3.5, True, "Great question, thinking about this one."),
    ]),
    ("growth_gabi", [
        (3.2, False, "Hi! I run a marketing agency, we'd love to collab on a sponsored post. DM me rates?"),
    ]),
    ("cfo_carlos", [
        (2.8, False, "How do I justify GenAI spend to the board? Need a framework for ROI on AI projects. Video please!"),
    ]),
    ("ml_maya", [
        (2.4, False, "LangGraph or CrewAI or build your own? Would love your honest comparison of agent frameworks"),
        (1.2, False, "And a follow up: how do you test agents? Unit testing LLM calls feels impossible"),
    ]),
    ("newbie_nick", [
        (1.7, False, "thanks for the videos man, learned a ton"),
    ]),
    ("arch_aisha", [
        (1.1, False, "Suggestion: how to write a PRD for an LLM feature - acceptance criteria, evals, guardrails. PMs on my team struggle with this."),
        (0.4, False, "One more: what does an AI ROI business case actually look like? Templates would be amazing."),
    ]),
]


def demo_threads() -> list[Thread]:
    now = datetime.now(timezone.utc)
    threads: list[Thread] = []
    for i, (username, msgs) in enumerate(_THREADS, start=1):
        thread_id = f"demo-thread-{i}"
        messages: list[Message] = []
        for j, (days_ago, from_me, text) in enumerate(msgs, start=1):
            messages.append(
                Message(
                    id=f"demo-msg-{i}-{j}",
                    thread_id=thread_id,
                    text=text,
                    created_time=now - timedelta(days=days_ago),
                    sender_id="me" if from_me else f"demo-user-{i}",
                    sender_username="you" if from_me else username,
                    from_me=from_me,
                )
            )
        messages.sort(key=lambda m: m.created_time)
        threads.append(
            Thread(
                id=thread_id,
                updated_time=messages[-1].created_time,
                participant_id=f"demo-user-{i}",
                participant_username=username,
                messages=messages,
            )
        )
    threads.sort(key=lambda t: t.updated_time, reverse=True)
    return threads
