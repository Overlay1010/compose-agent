from app.midi_io.convert import midi_bytes_to_project


def upload(client, data, name="song.mid"):
    return client.post("/api/v1/projects", files={"file": (name, data, "audio/midi")})


def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_upload_get_summary_export(client, midi_bytes):
    r = upload(client, midi_bytes, "내 곡.mid")
    assert r.status_code == 200
    project = r.json()
    assert project["name"] == "내 곡"
    assert project["version"] == 1
    pid = project["id"]

    assert client.get(f"/api/v1/projects/{pid}").json()["id"] == pid

    summary = client.get(f"/api/v1/projects/{pid}/summary").json()
    assert summary["bar_count"] == 4
    assert {t["name"]: t["note_count"] for t in summary["tracks"]} == {"Piano": 12, "Bass": 8, "Drums": 16}

    exp = client.get(f"/api/v1/projects/{pid}/export")
    assert exp.status_code == 200
    assert exp.headers["content-type"] == "audio/midi"
    assert len(midi_bytes_to_project(exp.content).tracks) == 3


def test_rejects_wrong_extension(client, midi_bytes):
    r = upload(client, midi_bytes, "song.wav")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_file_type"


def test_rejects_broken_midi(client):
    r = upload(client, b"garbage", "song.mid")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "midi_parse_failed"


def test_unknown_project(client):
    r = client.get("/api/v1/projects/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "project_not_found"
