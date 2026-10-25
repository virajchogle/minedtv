# MinedTV

Gaming clip app with plain-language search over your gameplay ("the clutch on Bind") that jumps to the exact second. Built for the Medal.tv hackathon.

- [`backend/`](backend/): FastAPI + Postgres/pgvector + R2 + RQ worker + Modal GPU inference, plus a Gemini-powered video-to-content engine. See [backend/README.md](backend/README.md).
- Web app (live): https://minedtv.vercel.app (`frontend/`, deployed by Vercel on every push to `main`)
- Android UI: https://github.com/rishikesh-web/MinedTv
- Mock API responses for UI work: [`backend/docs/api-examples/`](backend/docs/api-examples/)
- Who owns what and open work: [NOTES.md](NOTES.md)
