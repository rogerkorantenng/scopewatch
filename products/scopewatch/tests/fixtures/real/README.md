# Real-footage fixtures

Small crops from openly licensed laparoscopic and surgical videos, kept so the defects
found on real footage stay fixed. No whole clip is stored here. Each crop was cut from
a frame of a video transcoded from the source below; nothing was colour-adjusted.

| File | What it pins down | Source | Credit | Licence |
|---|---|---|---|---|
| `wses-pool-1050-crop.png`, `wses-pool-1050-crop-label.png` | A pooled-blood field that the old segmenter read as 0%. The label is hand-drawn (255 blood, 128 ignore). | [Commons file](https://commons.wikimedia.org/wiki/File:Diagnosis-and-treatment-of-perforated-or-bleeding-peptic-ulcers-2013-WSES-position-paper-1749-7922-9-45-S1.ogv), frame 1050 | Di Saverio S et al., "Diagnosis and treatment of perforated or bleeding peptic ulcers: 2013 WSES position paper", World J Emerg Surg 2014, doi:10.1186/1749-7922-9-45 | CC BY 4.0 |
| `wses-shaft-8s-crop.png` | A wet steel shaft whose bright-stripe mask is half its true width. | same file, frame 240 | same | CC BY 4.0 |
| `barroso-rim-827-crop.png` | Shadowed peritoneum at the rim of the scope's circle, read as blood by the old segmenter. | [Commons file](https://commons.wikimedia.org/wiki/File:Learning-Curves-for-Laparoscopic-Repair-of-Inguinal-Hernia-and-Communicating-Hydrocele-in-Children-video_1.ogv), frame 827 | Barroso C et al., "Learning Curves for Laparoscopic Repair of Inguinal Hernia and Communicating Hydrocele in Children", Front Pediatr 2017, doi:10.3389/fped.2017.00207 | CC BY 4.0 |
| `kavalakat-port-1650-crop.png` | The inside of a port sleeve, read as blood by the old segmenter. | [Commons file](https://commons.wikimedia.org/wiki/File:Laparoscopic-management-of-an-uncommon-cause-for-right-lower-quadrant-pain-A-case-report-1757-1626-1-164-S1.ogv), frame 1650 | Kavalakat A, Varghese C, "Laparoscopic management of an uncommon cause for right lower quadrant pain: A case report", Cases J 2008, doi:10.1186/1757-1626-1-164 | CC BY 2.0 |
| `gupta-glove-1019-crop.png` | Gloved fingers in an open abdomen, which must be refused as out of domain. | [Commons file](https://commons.wikimedia.org/wiki/File:Torsion-of-gall-bladder-a-rare-entity-a-case-report-and-review-article-1757-1626-2-193-S1.ogv), frame 1019 | Gupta V, Singh V, Sewkani A, Purohit D, Varshney R, Varshney S, "Torsion of gall bladder, a rare entity: a case report and review article", Cases J 2009, doi:10.1186/1757-1626-2-193 | CC BY 2.0 |

The blood labels in `eval/real/blood-labels.json` are polygons drawn over frames of
all sixteen clips listed in `src/scopewatch/realdata.py`, which carries each clip's
source page, credit and licence. Four of those clips (Anpol42, Wikimedia Commons) are
CC BY-SA 3.0; labels derived from them are shared under the same licence.
