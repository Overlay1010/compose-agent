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


def test_export_one_track_and_zip(client):
    import io
    import zipfile

    from app.models.project import Note, Project, Track
    from app.store.memory import store

    p = store.create(Project(id="exp1", name="내 곡: 1/2", tempo=90, tracks=[
        Track(id="t1", name="Drums", is_drum=True, notes=[Note(pitch=36, start=0, duration=0.5)]),
        Track(id="t2", name="탑노트", program=73, program_set=True, volume=80, notes=[Note(pitch=72, start=4, duration=1)]),
    ]))
    one = client.get(f"/api/v1/projects/{p.id}/export", params={"track": "t2"})
    assert one.status_code == 200 and one.content[:4] == b"MThd"
    assert "%ED%83%91%EB%85%B8%ED%8A%B8" in one.headers["content-disposition"]  # 탑노트
    back = midi_bytes_to_project(one.content)
    assert [(t.name, t.program, t.volume, t.notes[0].start) for t in back.tracks] == [("탑노트", 73, 80, 4.0)]
    assert round(back.tempo) == 90
    assert client.get(f"/api/v1/projects/{p.id}/export", params={"track": "t9"}).status_code == 404

    z = client.get(f"/api/v1/projects/{p.id}/export/tracks")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    files = zipfile.ZipFile(io.BytesIO(z.content))
    assert files.namelist() == ["00 전체 곡 - 내 곡_ 1_2.mid", "01 Drums.mid", "02 탑노트.mid"]
    drums = midi_bytes_to_project(files.read("01 Drums.mid"))
    assert drums.tracks[0].is_drum and len(drums.tracks) == 1
