# mpegts-audio-processing
Sample project showing how to get mpegts audio and process it in python. The
processing here is just printing the timestamp and data of the buffers.

It requires a file named sample.ts to be copied to the root of the project.
This can be easily adjusted to use volumes from docker to access your local
host files, if needed.

Build with docker:
docker build -t mpegts-audio-processing .

Then run with:
docker run --rm mpegts-audio-processing

You can also configure channels and sample format with env vars:
docker run --rm -e channels=2 -e sampleformat=S16LE mpegts-audio-processing

