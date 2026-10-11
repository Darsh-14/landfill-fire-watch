# WeSave

**Track:** Waste and Energy · **Repo:** this repository · **Video:** (link after upload)

## Problem

Landfill fires in Indian cities push smoke into crowded neighbourhoods. At Deonar, Mumbai, in January 2016 the
fire burned for about four days and more than 70 schools closed. At Brahmapuram, Kochi, in March 2023 smoke spread
up to about 10 km and classes for younger students were suspended. India's satellite fire alerts are built for
forests: the Forest Survey of India filters out all fires other than forest fires. We found no service that tells
a city duty officer, or the schools downwind, that a landfill is showing a satellite hotspot.

## What we built

Every three hours a scheduled scan pulls NASA FIRMS hotspots (VIIRS and MODIS) for all of India. Deterministic
Python matches each hotspot to landfill outlines from OpenStreetMap, using a buffer sized to the satellite pixel,
groups hotspots into incidents and sets the status (CANDIDATE or PROBABLE) with fixed rules. It then draws a smoke
*screening sector* from Open-Meteo wind and lists the schools and hospitals inside it, with distances.

A Strands agent on Amazon Bedrock turns those computed facts into a resident advisory and an official alert. The
agent has only read-only tools. An 11-check validator rejects any draft that names a place that is not in the
computed list, changes a number, says "confirmed", makes health claims, or drops the `[REPLAY]` label. The agent
gets one retry with the error list; then a fixed template is used. A person must approve every message before
SNS emails it, and historical replays can only go to a demo topic. The dashboard shows data age, the satellites used
and the replay label at all times. The limits are listed below.

## Where AWS fits

EventBridge Scheduler triggers the scan Lambda; raw FIRMS CSVs go to S3 with their SHA-256; scans, detections and
incidents live in DynamoDB; an HTTP API (API Gateway + Lambda, throttled) serves the dashboard on Amplify Hosting;
the drafting Lambda calls Bedrock through Strands; SNS sends approved alerts; secrets sit in SSM Parameter Store;
CloudWatch holds JSON-line logs of every agent tool call and validator result. We deploy with AWS SAM.

## Results

With rules frozen before the first run, we replayed three documented fires from the FIRMS archive. Deonar 2016
was detected one day (IST) after the reported start and Brahmapuram 2023 on the same day. **We missed Ghazipur
2022:** the satellites saw heat on the landfill on only one overpass, so the system raised a candidate, not a
probable fire. Six 30-day monsoon windows with no reported fire produced zero alerts — weak evidence, because
monsoon cloud also hides fires.

## Limits

Surface fires only; 375 m to 1 km pixels, so nearby heat sources can trigger hotspots; cloud and smoke block
detection; a detection is not a confirmation; the smoke sector is not a pollution forecast. The outlines were
checked on imagery by our AI coding agent, not yet by a person on the ground, and no rule text is verified yet.

## AI coding tools

Claude Code (Anthropic's Claude) wrote the code, tests and documentation with the team.

The demo video narration is synthesised with Amazon Polly (neural voice Kajal, Indian English).
