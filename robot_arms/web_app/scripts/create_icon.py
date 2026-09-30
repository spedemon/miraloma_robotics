"""Create platform icon files from Mira's source logo."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: create_icon.py SOURCE.png OUTPUT.icns|OUTPUT.ico")

    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(source).convert("RGBA")
    if image.width != image.height:
        side = max(image.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
        image = square

    if output.suffix.lower() == ".icns":
        image.resize((1024, 1024), Image.Resampling.LANCZOS).save(output, format="ICNS")
    elif output.suffix.lower() == ".ico":
        image.save(
            output,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    else:
        raise SystemExit(f"unsupported icon format: {output.suffix}")


if __name__ == "__main__":
    main()
