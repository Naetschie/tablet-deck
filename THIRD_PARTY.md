# Fremde Bestandteile

Tablet Deck selbst steht unter der GNU General Public License v3.0 (`LICENSE`).

## Im Repo enthalten
| Bestandteil | Ort | Lizenz | Lizenztext |
|---|---|---|---|
| Icon-Formen nach [Lucide](https://lucide.dev) (teils aus Feather) | `web/lib/icons.svg` | ISC bzw. MIT (Feather) | `web/lib/LICENSE-lucide.txt` |
| Schrift [Inter](https://github.com/rsms/inter) | `web/lib/fonts/inter-latin-var.woff2` | SIL Open Font License 1.1 | `web/lib/fonts/OFL-Inter.txt` |
| Schrift [Space Grotesk](https://github.com/floriankarsten/space-grotesk) | `web/lib/fonts/space-grotesk-latin-var.woff2` | SIL Open Font License 1.1 | `web/lib/fonts/OFL-SpaceGrotesk.txt` |

## Bei der Installation geladen (nicht im Repo)
| Bestandteil | Woher | Lizenz |
|---|---|---|
| websockets, psutil, pycparser | pip | BSD-3-Clause |
| pyserial, nvidia-ml-py | pip | BSD |
| pycaw, pythonnet | pip | MIT |
| cffi | pip | MIT-0 |
| clr_loader | pip | MIT |
| pillow | pip | MIT-CMU |
| pystray | pip | LGPL-3.0 |
| cryptography | pip | Apache-2.0 oder BSD-3-Clause |
| anthropic | pip | Apache-2.0 |
| HardwareMonitor (bringt LibreHardwareMonitorLib mit) | pip | BSD-3-Clause; LibreHardwareMonitor: MPL-2.0 |
| PresentMon | GitHub-Release von Intel (`scripts/install-sensors.ps1`) | MIT |
| Android platform-tools (adb) | Google (`install.ps1`) | Android SDK-Lizenz |
| PawnIO-Treiber | winget (`namazso.PawnIO`) | eigene Lizenz des Projekts |

## Nicht enthalten
- **Spieldateien:** Das Star-Citizen-Standardprofil (`tools/sc/…`) wird aus der eigenen Installation erzeugt
  (`docs/star-citizen.md`) und nicht weitergegeben.
- **Karten:** Die Karten-Kachel verlinkt auf Map Genie und andere Seiten; deren Inhalte werden nicht kopiert.
