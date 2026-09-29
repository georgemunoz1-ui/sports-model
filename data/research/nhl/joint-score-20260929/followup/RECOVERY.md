Reconstruct followup archive from an evidence-branch checkout:

```sh
cat followup-archive/followup.zip.part* > followup-evidence.zip
sha256sum followup-evidence.zip
```

Expected SHA256: `eb744f0597cd72f51df912c2a9af7919df1784415ac8d56b46791cccd731f973`. Exactly 52 parts, 40697351 bytes. Check the hash before extraction. Original 15-forecast archive has its separate recovery script and hash.
