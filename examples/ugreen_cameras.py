"""Capture from configured hardware only after supplying a commissioned bench file."""

import argparse
from pathlib import Path

from pytestlab import Bench


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", type=Path, required=True)
    args = parser.parse_args()
    with Bench.open(args.bench, aliases={"bench_camera", "bench_camera_2k"}) as bench:
        bench.bench_camera.capture().save("ugreen-camera.jpg")
        bench.bench_camera_2k.capture().save("ugreen-camera-2k.jpg")


if __name__ == "__main__":
    main()
