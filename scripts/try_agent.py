"""Run the default zero-cost demo against public APIs and print its trace."""

import argparse
import asyncio
import json

from cwa.config import Settings
from cwa.runtime import build_runner
from cwa.store.db import Database


async def run(question: str) -> None:
    """Use only the free rules provider; public data APIs may be called."""
    settings = Settings(provider="demo", db_path=":memory:")
    store = Database(":memory:")
    runner = build_runner(settings, store, question)
    result = await runner.run(question)
    store.save_run(result, None, question)
    print("Answer:")
    print(result.answer.model_dump_json(indent=2))
    print("\nTrace:")
    print(json.dumps([step.model_dump(mode="json") for step in result.trace], indent=2))
    store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "question",
        nargs="?",
        default="When should I charge my EV in RG1 tonight for 4 hours?",
    )
    asyncio.run(run(parser.parse_args().question))


if __name__ == "__main__":
    main()
