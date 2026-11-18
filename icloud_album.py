#!/usr/bin/env python3
"""Download every original photo and video from a public iCloud shared album.

Works with public shared album links on photos.icloud.com (the ones with
/shared/album/ in them) and needs no Apple account: it makes the same
anonymous web requests the album page makes in a browser. Files
that already exist in the output folder are skipped, so an interrupted run can
be started again. Standard library only.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HEADERS = {"Content-Type": "text/plain", "Origin": "https://photos.icloud.com"}
RESOLVE = ("https://ckdatabasews.icloud.com/database/1/com.apple.photos.cloud/production/public/records/resolve"
           "?remapEnums=true&sharing_url_key={key}")
PAGE = 200  # records requested per page


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from iCloud: {e.read()[:300].decode(errors='replace')}")


def album_key(text):
    """Accept the key on its own or the full album link, and return the key."""
    text = text.strip()
    if "://" in text:
        u = urllib.parse.urlparse(text)
        text = u.fragment or u.path.rstrip("/").rsplit("/", 1)[-1]
    return text


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("album", help="the shared album link, or just the key at the end of it")
    p.add_argument("out_dir", help="folder to download into (created if missing)")
    a = p.parse_args()

    key = album_key(a.album)
    if not key:
        p.error("could not find an album key in that link")
    os.makedirs(a.out_dir, exist_ok=True)

    results = post(RESOLVE.format(key=urllib.parse.quote(key)), {"shortGUIDs": [{"value": key}]}).get("results") or [{}]
    r = results[0]
    if "anonymousPublicAccess" not in r:
        sys.exit(f"album not found or not public: {r.get('reason') or r.get('serverErrorCode') or 'no public access returned'}")
    access, zone = r["anonymousPublicAccess"], r["zoneID"]
    q = urllib.parse.urlencode({"remapEnums": "true", "sharing_url_key": key, "publicAccessAuthToken": access["token"]})
    base = f"{access['databasePartition']}/database/1/com.apple.photos.cloud/production/shared/records/query?{q}"

    records, marker = [], None
    while True:
        body = {"query": {"recordType": "CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted",
                          "filterBy": [{"fieldName": "direction", "comparator": "EQUALS",
                                        "fieldValue": {"type": "STRING", "value": "ASCENDING"}}]},
                "zoneID": zone, "resultsLimit": PAGE}
        if marker:
            body["continuationMarker"] = marker
        d = post(base, body)
        records += d.get("records", [])
        marker = d.get("continuationMarker")
        if not marker:
            break

    masters = {x["recordName"]: x for x in records if x.get("recordType") == "CPLMaster"}
    print(f"{len(records)} records, {len(masters)} originals")
    got = skipped = 0
    for name, m in masters.items():
        f = m["fields"]
        # a video keeps its full-quality file in resOriginalVidComplRes; photos use resOriginalRes
        res = f.get("resOriginalVidComplRes") or f.get("resOriginalRes")
        if not res:
            print("skip (no original)", name)
            continue
        enc = f.get("filenameEnc", {}).get("value")
        fn = base64.b64decode(enc).decode() if enc else name
        fn = os.path.basename(fn.replace("\\", "/")) or name  # never write outside the output folder
        dest = os.path.join(a.out_dir, fn)
        if os.path.exists(dest):
            skipped += 1
            continue
        url = res["value"]["downloadURL"].replace("${f}", urllib.parse.quote(fn))
        part = dest + ".part"
        urllib.request.urlretrieve(url, part)
        os.replace(part, dest)
        got += 1
        print("got", fn, os.path.getsize(dest))
    print(f"downloaded {got}, already present {skipped}")


if __name__ == "__main__":
    sys.exit(main())
