"""What a worker can do. Each handler takes the job input as a string and returns a string.

Two kinds on purpose: one that waits on the network and the model, one that burns CPU.
"""

import re

import httpx
from langchain_core.messages import HumanMessage


def count_primes(input: str) -> str:
    """CPU work, done the slow way on purpose so a worker is visibly busy for a few seconds.

    count_primes("1000000") takes about three seconds. Watch the task's CPU graph later.
    """
    n = int(input)
    count = 0
    for candidate in range(2, n + 1):
        is_prime = True
        for divisor in range(2, int(candidate**0.5) + 1):
            if candidate % divisor == 0:
                is_prime = False
                break
        count += is_prime
    return f"{count} primes below {n}"


def summarise_url(input: str, llm) -> str:
    """Network work, then a model call. Fetch a page, strip the tags, ask for two sentences."""
    page = httpx.get(
        input, timeout=20, follow_redirects=True, headers={"User-Agent": "mission-control"}
    )
    page.raise_for_status()
    text = re.sub(r"<[^>]+>", " ", page.text)
    text = re.sub(r"\s+", " ", text)[:6000]
    reply = llm.invoke([HumanMessage(content=f"Summarise this page in two sentences:\n\n{text}")])
    return reply.content if isinstance(reply.content, str) else str(reply.content)


def run(job_kind: str, job_input: str, llm) -> str:
    if job_kind == "count_primes":
        return count_primes(job_input)
    if job_kind == "summarise_url":
        return summarise_url(job_input, llm)
    raise ValueError(f"unknown job kind {job_kind}")
