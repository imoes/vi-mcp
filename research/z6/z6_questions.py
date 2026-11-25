"""Z6 (goal catalogue): two-hop questions over the VI's inventory facts (vi-facts kb.lp, parsed by rules from the VI's own inventory
pages, no model). A question names a VM; its answer needs the VM's page (which node hosts it: kb(VM, "pve_host", node)) AND the node's
page (a property of the node). Gold = the two page object ids (kb_src). Only VMs whose node has its own inventory page qualify; the
node's page is kept only when the node's name does not occur in the question (it never does: the question names only the VM).
Questions are template sentences in German and English, written before any search ran (named limit: template wording).
VMs whose short name belongs to more than one inventory page are left out (the question would be ambiguous; found on development
data: a page with a misspelt domain) — AFTER the split, so every VM keeps the side it had in the first build. Split by VM: random.Random("z6-split-2026-11-22"), half development, half test.
usage: z6_questions.py KB.lp OUT_DIR   (OUT_DIR on our hosts only — the questions contain internal host names)"""
import json
import random
import re
import sys
from pathlib import Path

PAT = re.compile(r'^(kb|kb_src|kb_ip|kb_container)\((.*)\)\.$')
TEMPLATES = {
    "os": ["Welches Betriebssystem läuft auf dem Proxmox-Host, auf dem die VM {vm} läuft?",
           "Which operating system runs on the Proxmox node that hosts the VM {vm}?"],
    "gateway": ["Welches Gateway hat der Hypervisor, auf dem {vm} läuft?",
                "What is the gateway of the hypervisor where {vm} is running?"],
    "ip": ["Welche IP-Adressen hat der Node, der die VM {vm} hostet?",
           "Which IP addresses does the node hosting the VM {vm} have?"],
    "container": ["Welche Docker-Container laufen auf dem Host, auf dem die VM {vm} liegt?",
                  "Which Docker containers run on the host that runs the VM {vm}?"],
}


def args(s):
    return json.loads("[" + s + "]")


def main():
    kb_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    kb, src, ips, cont = {}, {}, {}, {}
    for line in kb_path.read_text().splitlines():
        m = PAT.match(line.strip())
        if not m:
            continue
        kind, a = m.group(1), args(m.group(2))
        if kind == "kb":
            kb.setdefault(a[0], {}).setdefault(a[1], a[2])
        elif kind == "kb_src":
            src[a[0]] = a[1]
        elif kind == "kb_ip":
            ips.setdefault(a[0], []).append(a[1])
        elif kind == "kb_container":
            cont.setdefault(a[0], []).append(a[1])
    by_short = {}
    for h in src:
        by_short.setdefault(h.split(".")[0], set()).add(h)
    short = {k: next(iter(v)) for k, v in by_short.items() if len(v) == 1}
    ambiguous = {k for k, v in by_short.items() if len(v) > 1}   # e.g. a page with a misspelt domain: the VM name is ambiguous
    items = []
    for vm, props in sorted(kb.items()):
        node_short = props.get("pve_host")
        node = short.get(node_short or "")
        if not node or vm not in src or node == vm or src[node] == src[vm]:
            continue
        have = {"os": bool(kb.get(node, {}).get("os")), "gateway": bool(kb.get(node, {}).get("gateway")),
                "ip": bool(ips.get(node)), "container": bool(cont.get(node))}
        vm_name = vm.split(".")[0]
        for rel, ok in have.items():
            if not ok:
                continue
            for lang, tpl in zip(("de", "en"), TEMPLATES[rel]):
                items.append({"id": f"z6:{vm_name}:{rel}:{lang}", "vm": vm, "node": node, "relation": rel, "lang": lang,
                              "question": tpl.format(vm=vm_name), "gold": [src[vm], src[node]], "_amb": vm_name in ambiguous})
    vms = sorted({i["vm"] for i in items})
    rnd = random.Random("z6-split-2026-11-22")
    test_vms = set(rnd.sample(vms, len(vms) // 2))   # split over ALL VMs (as in the first build), ambiguous ones dropped after it
    items = [{k: v for k, v in i.items() if k != "_amb"} for i in items if not i["_amb"]]
    out.mkdir(parents=True, exist_ok=True)
    for name, sel in (("dev", lambda i: i["vm"] not in test_vms), ("test", lambda i: i["vm"] in test_vms)):
        rows = [i for i in items if sel(i)]
        (out / f"z6_{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        print(name, len(rows), "items over", len({r["vm"] for r in rows}), "VMs")


if __name__ == "__main__":
    main()
