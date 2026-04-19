# BahayCubo

Bahay Cubo is a home for all cubers.

**Bahay** means *home* in Tagalog. **Kubo** is the nipa hut — a simple, welcoming space where everyone belongs.

*Just come in, train, and leave when you're done. Or stay and be a part of something.*

Live at [bahaycubo.io](https://bahaycubo.io)

---

## Apps

### Cubo Cross (`/cubocross`)

A web-based training tool for speedcubers who want to get better at recognizing and executing **cross** and **xcross** (extended cross) solutions during inspection.

Every session gives you a random WCA-style scramble and instantly computes:

- The **optimal cross** solution
- The optimal **xcross** solution for each of the four F2L slots — BR, RG, GO, and OB

You can compare move counts across all five options side by side.

The 3D cube highlights only the pieces relevant to the cross or xcross you're looking at while greying everything else out.

**Features**

- **Optimal solutions** via IDA\* search backed by BFS-built pruning tables
- **5-way parallel solving** — cross + four xcross keys computed simultaneously
- **Interactive 3D cube** with hint faces, camera controls (mouse, touch, keyboard, D-pad)
- **Visualization modes** — toggle between cross-only and each xcross pair
- **Session history** stored in `localStorage`, organized by date with a date picker
- **Replay any past scramble** directly from history
- **Responsive layout** that works on desktop and mobile

#### Acknowledgments

Cubo Cross was inspired by Crystal Cuber's [Cross Trainer](https://crystalcuber.com/train/cross). Features like hint faces and solution revealing were inspired by that work. Thank you to Crystal Cuber for making it publicly available on [GitHub](https://github.com/crystalcuber/crystalcube) for the community to build upon.


---

## Tech stack

| Layer | Details |
|---|---|
| Backend | Python 3, Flask |
| Frontend | HTML5, CSS3, vanilla JavaScript |
| Serving | Gunicorn + Nginx (production) |
| Cube engine | Custom facelet representation (54 stickers), WCA move set + x/y/z rotations |
| Solver | Piece-based encodings, BFS pruning tables, IDA\* |
| Scrambler | Custom WCA-style 20-move random state scrambler |
| Streaming | NDJSON over `fetch` + `ReadableStream` |

---

## Getting started

**Requirements:** Python 3.8+ and Flask.

```bash
# Clone the repo
git clone https://github.com/jregio/BahayCubo.git
cd BahayCubo

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

> **First run note:** On startup the Cubo Cross solver builds binary pruning tables under `apps/CuboCross/tables/` (one per cross/xcross key). This takes a bit of time and disk space the first time, but subsequent runs load them from cache and are much faster.

---

## Project structure

```
BahayCubo/
├── app.py                      # Flask app — registers blueprint, root routes
├── requirements.txt
├── templates/                  # Root-level Jinja2 templates
│   ├── base.html               # Shared layout (nav, fonts, head)
│   ├── landing.html
│   ├── webapps.html
│   ├── aboutme.html
│   └── contact.html
├── static/                     # Root-level static assets
│   ├── site.css                # Global stylesheet
│   ├── favicon.svg
│   ├── icons/                  # SVG icons (contact, location)
│   ├── images/                 # WebP images (profile, app screenshots)
│   ├── journey/                # SVG icons for the about me journey
│   └── videos/                 # MP4 for the about me journey finale
└── apps/
    └── CuboCross/              # Cubo Cross Flask Blueprint
        ├── __init__.py
        ├── routes.py           # Blueprint routes and streaming endpoint
        ├── cube.py             # Cube engine — facelets, moves, piece masks
        ├── solver.py           # Pruning tables and IDA* solver
        ├── scrambler.py        # WCA-style random scramble generator
        ├── templates/
        │   └── index.html      # Full UI + client-side JavaScript
        ├── static/
        │   └── style.css       # Cubo Cross stylesheet
        └── tables/             # Auto-generated pruning tables (gitignored)
```

