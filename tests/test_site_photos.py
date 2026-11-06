"""Site photos: documentation photos for a visit that are not report items.
Added in bulk, kept byte for byte, downloaded as a zip (alone or inside the
report zip) and removed from the server once that zip has fully gone out."""

import io
import os
import zipfile

import pytest
from PIL import Image

from webapp import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    data, uploads = tmp_path / "data", tmp_path / "uploads"
    data.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(server, "DATA_DIR", str(data))
    monkeypatch.setattr(server, "UPLOADS", str(uploads))
    monkeypatch.setattr(server, "PROJECTS_FILE", str(data / "projects.json"))
    monkeypatch.setattr(server, "LEGACY_DATA_FILE", str(data / "visit.json"))
    c = server.app.test_client()
    assert c.post("/login", data={"pin": server.PIN}).status_code == 302
    return c


def _visit(client):
    job = client.post("/api/jobs", json={"name": "Elm St Retrofit", "number": "24-117"}).get_json()
    r = client.post(f"/api/jobs/{job['job_id']}/visits", json={"visit_no": 3})
    assert r.status_code == 200, r.get_data(as_text=True)
    v = r.get_json()
    return job, v.get("visit", v)


def _jpeg(color, taken=None, size=(80, 60)):
    buf = io.BytesIO()
    im = Image.new("RGB", size, color)
    if taken:
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = taken          # DateTimeOriginal
        im.save(buf, "JPEG", quality=95, exif=exif)
    else:
        im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _add(client, pid, raw, name="IMG.jpg", **form):
    return client.post(f"/api/visits/{pid}/site-photos",
                       data={"photo": (io.BytesIO(raw), name), **form},
                       content_type="multipart/form-data")


def test_photos_are_kept_byte_for_byte_and_sorted_by_time_taken(client):
    _, v = _visit(client)
    pid = v["project_id"]
    late = _jpeg("red", "2026:11:06 14:30:00")
    early = _jpeg("blue", "2026:11:06 09:05:00")
    assert _add(client, pid, late, "late.jpg").get_json()["added"]["taken"] == "2026-11-06T14:30:00"
    _add(client, pid, early, "early.jpg")

    r = client.get(f"/api/visits/{pid}/site-photos").get_json()
    assert [p["original"] for p in r["photos"]] == ["early.jpg", "late.jpg"]
    assert r["summary"]["count"] == 2 and r["photos"][0]["thumb_url"]
    assert client.get(r["photos"][1]["url"]).data == late       # never re-encoded


def test_the_same_photo_is_skipped(client):
    _, v = _visit(client)
    pid = v["project_id"]
    raw = _jpeg("green")
    assert _add(client, pid, raw).get_json()["duplicate"] is False
    again = _add(client, pid, raw, "copy.jpg").get_json()
    assert again["duplicate"] is True and again["summary"]["count"] == 1


def test_download_zips_them_then_removes_them_from_the_server(client):
    job, v = _visit(client)
    pid = v["project_id"]
    a, b = _jpeg("red", "2026:11:06 10:00:00"), _jpeg("blue", "2026:11:06 11:00:00")
    _add(client, pid, a)
    _add(client, pid, b)

    built = client.post(f"/api/visits/{pid}/site-photos/build").get_json()
    assert built["count"] == 2 and built["name"] == "24-117 Elm St Retrofit SV3 site photos.zip"
    # building alone removes nothing
    assert client.get(f"/api/visits/{pid}/site-photos").get_json()["summary"]["count"] == 2

    r = client.get(built["url"])
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    assert zf.namelist() == ["SV3 2026-11-06 001.jpg", "SV3 2026-11-06 002.jpg"]
    assert zf.read("SV3 2026-11-06 001.jpg") == a                # full resolution
    assert zf.getinfo("SV3 2026-11-06 002.jpg").compress_type == zipfile.ZIP_STORED

    after = client.get(f"/api/visits/{pid}/site-photos").get_json()
    assert after["photos"] == [] and after["summary"]["downloaded"]["count"] == 2
    assert os.listdir(server.site_dir(pid)) == []
    # the zip stays a while, so it can be downloaded again
    assert after["summary"]["zip"]["count"] == 2
    assert zipfile.ZipFile(io.BytesIO(client.get(built["url"]).data)).namelist()
    # a photo already downloaded is not added a second time
    assert _add(client, pid, a).get_json()["duplicate"] is True
    # and the project page counts what is left
    visit = client.get(f"/api/jobs/{job['job_id']}").get_json()["visits"][0]
    assert visit["site_photos"]["count"] == 0 and visit["site_photos"]["downloaded"]["count"] == 2


def test_an_unfinished_download_removes_nothing(client):
    _, v = _visit(client)
    pid = v["project_id"]
    _add(client, pid, _jpeg("red"))
    built = client.post(f"/api/visits/{pid}/site-photos/build").get_json()

    r = client.get(built["url"], buffered=False)
    stream = iter(r.response)
    next(stream)              # the first part arrives, then the connection drops
    r.close()

    assert client.get(f"/api/visits/{pid}/site-photos").get_json()["summary"]["count"] == 1


def test_old_zips_expire(client, monkeypatch):
    _, v = _visit(client)
    pid = v["project_id"]
    _add(client, pid, _jpeg("red"))
    client.post(f"/api/visits/{pid}/site-photos/build")
    old = server.time.time() - 8 * 86400
    os.utime(server.site_zip_file(pid), (old, old))

    assert client.get(f"/api/visits/{pid}/site-photos").get_json()["summary"]["zip"] is None
    assert client.get(f"/api/visits/{pid}/site-photos/download").status_code == 404


def test_report_zip_carries_them_in_a_site_photos_folder(client):
    _, v = _visit(client)
    pid = v["project_id"]
    raw = _jpeg("red", "2026:11:06 10:00:00")
    _add(client, pid, raw)
    client.post(f"/api/projects/{pid}/open")

    built = client.post("/api/export/build").get_json()
    assert built["site_photos"] == 1
    zf = zipfile.ZipFile(io.BytesIO(client.get(built["url"]).data))
    folder = built["name"][:-4]
    assert zf.read(f"{folder}/Site photos/SV3 2026-11-06 001.jpg") == raw
    assert f"{folder}/site_visit_report.docx" in zf.namelist()
    assert client.get(f"/api/visits/{pid}/site-photos").get_json()["summary"]["count"] == 0


def test_delete_one(client):
    _, v = _visit(client)
    pid = v["project_id"]
    rec = _add(client, pid, _jpeg("red")).get_json()["added"]
    r = client.delete(f"/api/visits/{pid}/site-photos/{rec['site_id']}")
    assert r.get_json()["summary"]["count"] == 0
    assert client.delete(f"/api/visits/{pid}/site-photos/{rec['site_id']}").status_code == 404


def test_make_a_site_photo_an_item_and_back(client):
    _, v = _visit(client)
    pid = v["project_id"]
    raw = _jpeg("red")
    rec = _add(client, pid, raw, "crack.jpg").get_json()["added"]

    made = client.post(f"/api/visits/{pid}/site-photos/{rec['site_id']}/item").get_json()
    entry = made["entry"]
    assert made["summary"]["count"] == 0 and len(entry["images"]) == 1
    assert client.get(entry["images"][0]["url"]).data == raw

    client.post(f"/api/projects/{pid}/open")
    im = entry["images"][0]
    back = client.post(f"/api/item/{made['item_id']}/photo/{entry['photo_id']}"
                       f"/image/{im['image_id']}/site").get_json()
    # the item had nothing else in it, so it goes
    assert back["removed"] is True and back["summary"]["count"] == 1
    assert client.get("/api/visit").get_json()["items"] == []
    photos = client.get(f"/api/visits/{pid}/site-photos").get_json()["photos"]
    assert client.get(photos[0]["url"]).data == raw


def test_moving_a_photo_keeps_an_item_that_has_a_description(client):
    _, v = _visit(client)
    pid = v["project_id"]
    client.post(f"/api/projects/{pid}/open")
    item = client.post("/api/item").get_json()
    e = item["photos"][0]
    client.patch(f"/api/item/{item['item_id']}/photo/{e['photo_id']}", json={"description": "Crack"})
    e = client.post(f"/api/item/{item['item_id']}/photo",
                    data={"photo": (io.BytesIO(_jpeg("red")), "a.jpg"), "photo_id": e["photo_id"]},
                    content_type="multipart/form-data").get_json()

    back = client.post(f"/api/item/{item['item_id']}/photo/{e['photo_id']}"
                       f"/image/{e['images'][0]['image_id']}/site").get_json()
    assert back["removed"] is False and back["entry"]["images"] == []
    assert back["entry"]["description"] == "Crack"
