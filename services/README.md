# Services

These files come primarily from the apex-v3 / APEXCITADAEL lineage and are kept as optional HTTP microservices.

Suggested first boot:
- `python -m services.econopredator`
- `python -m services.newtonian`
- `python -m services.spoofhunter`
- `python -m services.antirug_v3`
- `python -m services.narrative`

The trading engine under `main.py` can stay usable without them; `core/fusion_registry.py`
is the first place to connect these outputs into the v666 runtime.
