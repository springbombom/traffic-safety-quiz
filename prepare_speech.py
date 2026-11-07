"""Regenerate the bundled Korean narration after editing questionnaire text."""
import asyncio
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

import edge_tts

from app import SPEECH_ARCHIVE, SPEECH_VOICE, load_data, speech_key


def narration_texts():
    texts = {"답을 하나 선택해 주세요."}
    order = ["첫 번째", "두 번째", "세 번째", "네 번째", "다섯 번째"]
    for test in load_data()["tests"]:
        for question in test["questions"]:
            texts.update((question["speech_text"], question["help_text"]))
            texts.add(" ".join(f"{ordinal}, {choice}."
                               for ordinal, choice in zip(order, question["choices"])))
            texts.update(f"선택하신 답은 {choice}입니다." for choice in question["choices"])
    return sorted(text.strip() for text in texts)


async def prepare():
    manifest = []
    semaphore = asyncio.Semaphore(2)
    with tempfile.TemporaryDirectory(dir=SPEECH_ARCHIVE.parent) as directory:
        output = Path(directory)

        async def generate(text, rate):
            async with semaphore:
                key = speech_key(text, rate)
                path = output / f"{key}.mp3"
                for attempt in range(3):
                    try:
                        speech = edge_tts.Communicate(
                            text, SPEECH_VOICE, rate="-25%" if rate == "slow" else "-10%")
                        await asyncio.wait_for(speech.save(str(path)), timeout=30)
                        if path.stat().st_size <= 44:
                            raise OSError("Empty narration")
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2)
                manifest.append({"key": key, "rate": rate, "text": text})
                print(f"Generated {len(manifest)} narration files", flush=True)

        await asyncio.gather(*(generate(text, rate) for text in narration_texts()
                               for rate in ("normal", "slow")))
        pending = output / "speech_audio.zip"
        with ZipFile(pending, "w", compression=ZIP_STORED) as archive:
            for item in sorted(manifest, key=lambda item: item["key"]):
                filename = f"{item['key']}.mp3"
                archive.write(output / filename, filename)
            archive.writestr("manifest.json", json.dumps(
                {"voice": SPEECH_VOICE, "items": manifest}, ensure_ascii=False))
        pending.replace(SPEECH_ARCHIVE)
    print(f"Saved {len(manifest)} narration files to {SPEECH_ARCHIVE}", flush=True)


if __name__ == "__main__":
    asyncio.run(prepare())
