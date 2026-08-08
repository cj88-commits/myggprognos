# Geographic benchmark — after-calibrated

Computed fresh at `2026-08-08T10:01:38.162666+00:00` from real static features (`data/static/cell_features.json`) and a live weather fetch for 55 benchmark locations (`forecast/benchmarks/locations.json`), all evaluated at the same instant so differences are attributable to geography/weather-history, not time-of-day. Full data: `data/generated/diagnostics/geographic-benchmark-after-calibrated.csv`.

## Contrast pairs

No target ratios are hard-coded here (per spec) -- these numbers are reported as evidence, not asserted against a threshold.

| Contrast | Higher-expected location | population_potential | Lower-expected location | population_potential | ratio | final_risk ratio |
|---|---|---|---|---|---|---|
| Dalarna skog / Stockholm centrum | Dalarna skog (Alvdalen) | 15.8 | Stockholm centrum | 14.3 | 1.10x | 1.19x |
| Siljan strand / Stockholm centrum | Siljan strand (Rattvik) | 14.3 | Stockholm centrum | 14.3 | 1.00x | 1.00x |
| Osterfarnebo (Lower Dalalven) / Stockholm centrum | Osterfarnebo | 25.4 | Stockholm centrum | 14.3 | 1.78x | 1.98x |
| Norrbotten vat barrskog / Stockholm centrum | Norrbotten vat barrskog (Jokkmokk) | 15.4 | Stockholm centrum | 14.3 | 1.08x | 1.19x |
| Norrbotten vatmark / Harjedalen fjall | Norrbotten vatmark (Muddus/Sjaunja) | 17.0 | Harjedalen fjall (Funasdalen) | 15.7 | 1.08x | 0.94x |
| Vanern strand / Vanern oppet vatten | Vanern strand (Lidkoping) | 15.5 | Vanern oppet vatten | 13.2 | 1.18x | 1.17x |
| Store Mosse (wetland) / Malardalen jordbruksbygd (farmland) | Store Mosse nationalpark | 18.2 | Malardalen jordbruksbygd (Enkoping) | 14.1 | 1.29x | 1.50x |
| Vasterbottens inland (forest) / Stockholm centrum | Vasterbottens inland (Lycksele) | 16.9 | Stockholm centrum | 14.3 | 1.18x | 1.28x |
| Bohuslan (exposed coast) / Varmland skog och sjo (sheltered lake) | Varmland skog och sjo (Sunne, Frykensjoarna) | 15.4 | Bohuslan (Fjallbacka) | 16.0 | 0.96x | 1.08x |

## Distribution across all benchmark locations

- `population_potential` (Myggläge): min 6.6, p25 14.1, median 15.3, p75 16.6, max 25.4, mean 15.5
- `final_risk` (Myggrisk, this instant): min 2.0, p25 4.9, median 5.4, p75 6.3, max 10.1, mean 5.6

## Full table

| Location | Category | forest | wetland | water | urban | dist_water_km | elevation_m | pop_potential | activity | exposure | final_risk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Stockholm centrum | urban centre | 0.19 | 0.00 | 0.20 | 0.51 | 0.3 | 9 | 14.3 | 3.5 | 59.7 | 5.1 |
| Stockholms skargard (Vaxholm) | archipelago | 0.31 | 0.01 | 0.54 | 0.07 | 0.3 | 23 | 14.9 | 4.0 | 67.0 | 5.6 |
| Uppsala | major city | 0.20 | 0.00 | 0.00 | 0.40 | 4.5 | 12 | 13.8 | 3.2 | 34.1 | 4.3 |
| Osterfarnebo | dense inland forest | 0.37 | 0.27 | 0.38 | 0.01 | 0.1 | 52 | 25.4 | 6.2 | 69.6 | 10.1 |
| Linkoping | major city | 0.38 | 0.02 | 0.01 | 0.24 | 1.4 | 74 | 14.7 | 1.6 | 55.9 | 4.9 |
| Store Mosse nationalpark | wetland / floodplain | 0.52 | 0.54 | 0.01 | 0.02 | 1.3 | 175 | 18.2 | 5.1 | 61.9 | 6.8 |
| Goteborg kustlinje | exposed west coast | 0.34 | 0.01 | 0.01 | 0.46 | 2.5 | 47 | 13.5 | 2.3 | 42.5 | 4.3 |
| Bohuslan (Fjallbacka) | exposed west coast | 0.28 | 0.02 | 0.28 | 0.05 | 0.3 | 9 | 16.0 | 0.6 | 66.9 | 5.6 |
| Malmo | major city | 0.14 | 0.00 | 0.10 | 0.60 | 1.4 | 8 | 14.1 | 3.5 | 48.0 | 4.7 |
| Vanern strand (Lidkoping) | lake shore | 0.31 | 0.02 | 0.14 | 0.13 | 1.3 | 60 | 15.5 | 1.4 | 57.8 | 5.2 |
| Vattern strand (Granna) | lake shore | 0.22 | 0.01 | 0.53 | 0.04 | 0.1 | 92 | 21.8 | 1.5 | 67.3 | 7.7 |
| Gotland (Visby) | island | 0.31 | 0.00 | 0.14 | 0.25 | 1.7 | 50 | 14.8 | 3.6 | 52.0 | 5.1 |
| Gotland (Faro) | island / exposed coast | 0.35 | 0.06 | 0.22 | 0.03 | 0.3 | 7 | 17.9 | 2.1 | 68.2 | 6.5 |
| Oland (Borgholm) | island | 0.13 | 0.02 | 0.57 | 0.05 | 0.1 | 7 | 15.9 | 6.0 | 66.1 | 6.2 |
| Oland (Ottenby, sodra udden) | island / exposed coast | 0.12 | 0.07 | 0.45 | 0.01 | 1.2 | 8 | 15.0 | 1.6 | 57.7 | 5.1 |
| Umea | northern coast city | 0.28 | 0.00 | 0.08 | 0.34 | 0.1 | 6 | 15.3 | 3.4 | 64.3 | 5.6 |
| Lulea | northern coast city | 0.33 | 0.02 | 0.25 | 0.28 | 0.6 | 13 | 13.2 | 0.0 | 62.8 | 4.4 |
| Kiruna | far north | 0.44 | 0.07 | 0.10 | 0.22 | 1.1 | 552 | 11.9 | 5.7 | 60.2 | 4.5 |
| Abisko | far north / mountain | 0.36 | 0.00 | 0.34 | 0.01 | 0.7 | 372 | 11.3 | 5.6 | 65.5 | 4.3 |
| Are (fjallomrade) | mountain region | 0.41 | 0.05 | 0.01 | 0.03 | 2.8 | 1006 | 7.0 | 2.2 | 47.1 | 2.3 |
| Sarek nationalpark | mountain region / far north | 0.00 | 0.00 | 0.00 | 0.00 | 3.3 | 1229 | 6.6 | 1.5 | 39.4 | 2.0 |
| Smaland jordbruksbygd (Vaxjo) | farmland | 0.48 | 0.07 | 0.07 | 0.18 | 0.5 | 172 | 16.6 | 4.4 | 66.4 | 6.3 |
| Skane jordbruksbygd (Ystad) | farmland | 0.08 | 0.01 | 0.50 | 0.22 | 0.1 | 2 | 14.9 | 1.7 | 63.3 | 5.2 |
| Dalalven flodslatt | floodplain | 0.82 | 0.14 | 0.01 | 0.06 | 2.5 | 12 | 15.2 | 6.0 | 53.5 | 5.5 |
| Tornedalen (alvdal, floodplain) | floodplain / far north | 0.35 | 0.04 | 0.23 | 0.10 | 0.1 | 9 | 16.0 | 1.2 | 68.3 | 5.7 |
| Vastkusten skargard (Marstrand) | archipelago | 0.09 | 0.01 | 0.67 | 0.02 | 0.1 | 11 | 14.6 | 1.0 | 65.9 | 5.1 |
| Ostkusten skargard (Sandhamn) | archipelago | 0.26 | 0.01 | 0.71 | 0.00 | 0.1 | 9 | 14.8 | 7.0 | 68.4 | 5.9 |
| Sundsvall kustnara | northern coast city | 0.44 | 0.01 | 0.05 | 0.29 | 1.3 | 18 | 13.6 | 3.9 | 57.3 | 4.9 |
| Ornskoldsvik | northern coast city | 0.52 | 0.01 | 0.09 | 0.20 | 1.1 | 58 | 14.0 | 3.1 | 61.5 | 5.0 |
| Vasterbottens inland (Lycksele) | dense inland forest | 0.59 | 0.06 | 0.13 | 0.14 | 0.1 | 217 | 16.9 | 4.8 | 70.8 | 6.5 |
| Smalandsskog (Uppvidinge) | dense inland forest | 0.85 | 0.12 | 0.06 | 0.03 | 0.5 | 256 | 17.5 | 5.2 | 73.3 | 6.9 |
| Vasteras | major city | 0.18 | 0.01 | 0.36 | 0.29 | 0.1 | 3 | 19.5 | 1.0 | 63.6 | 6.7 |
| Orebro | major city | 0.27 | 0.06 | 0.03 | 0.35 | 1.5 | 31 | 15.6 | 2.0 | 52.4 | 5.2 |
| Kristianstad (vatmarker) | wetland / floodplain | 0.14 | 0.14 | 0.24 | 0.16 | 0.1 | 0 | 24.5 | 2.7 | 64.9 | 8.8 |
| Hjalstaviken (vatmark) | wetland / floodplain | 0.49 | 0.02 | 0.02 | 0.06 | 2.5 | 28 | 14.8 | 3.2 | 49.5 | 5.0 |
| Stockholm forort (Tyreso) | urban suburb | 0.47 | 0.03 | 0.08 | 0.25 | 1.7 | 53 | 15.6 | 4.4 | 54.1 | 5.5 |
| Mora (Siljan) | lake shore | 0.34 | 0.04 | 0.29 | 0.17 | 0.1 | 166 | 19.3 | 4.6 | 67.2 | 7.3 |
| Siljan strand (Rattvik) | lake shore | 0.63 | 0.03 | 0.06 | 0.11 | 2.3 | 193 | 14.3 | 5.1 | 52.5 | 5.1 |
| Dalarna skog (Alvdalen) | boreal forest | 0.76 | 0.05 | 0.05 | 0.07 | 1.3 | 287 | 15.8 | 6.0 | 64.0 | 6.1 |
| Varmland skog och sjo (Sunne, Frykensjoarna) | lake shore | 0.59 | 0.02 | 0.13 | 0.07 | 1.5 | 132 | 15.4 | 7.7 | 60.2 | 6.0 |
| Umea inland (Vindeln) | dense inland forest | 0.76 | 0.08 | 0.06 | 0.05 | 1.7 | 243 | 13.5 | 5.0 | 60.8 | 5.0 |
| Skelleftea | northern coast city | 0.47 | 0.02 | 0.05 | 0.21 | 0.7 | 23 | 15.4 | 3.0 | 64.3 | 5.5 |
| Overtornea (Tornealven) | floodplain / far north | 0.51 | 0.05 | 0.16 | 0.05 | 1.3 | 122 | 16.0 | 0.9 | 61.3 | 5.4 |
| Kiruna lagland (Torneträsk lagland) | far north lowland | 0.57 | 0.03 | 0.04 | 0.00 | 0.3 | 473 | 13.2 | 6.5 | 71.3 | 5.3 |
| Vanern oppet vatten | major open lake | 0.00 | 0.00 | 1.00 | 0.00 | 0.1 | 42 | 13.2 | 0.2 | 65.0 | 4.5 |
| Malaren oppet vatten | major open lake | 0.36 | 0.02 | 0.27 | 0.02 | 0.9 | 27 | 19.7 | 2.2 | 64.1 | 7.0 |
| Vattern oppet vatten | major open lake | 0.00 | 0.00 | 1.00 | 0.00 | 0.1 | 88 | 13.3 | 2.2 | 65.0 | 4.7 |
| Norrbotten vatmark (Muddus/Sjaunja) | wetland | 0.68 | 0.51 | 0.07 | 0.00 | 2.1 | 396 | 17.0 | 4.0 | 56.1 | 6.0 |
| Vasterbotten vat skog (Vilhelmina) | northern wet forest | 0.56 | 0.17 | 0.24 | 0.07 | 0.1 | 358 | 17.9 | 6.0 | 71.3 | 7.1 |
| Norrbotten vat barrskog (Jokkmokk) | northern wet forest | 0.74 | 0.13 | 0.05 | 0.07 | 0.5 | 243 | 15.4 | 5.9 | 71.3 | 6.1 |
| Skane jordbruksbygd (Lund) | farmland | 0.19 | 0.00 | 0.00 | 0.33 | 3.1 | 28 | 14.2 | 3.2 | 38.5 | 4.5 |
| Malardalen jordbruksbygd (Enkoping) | farmland | 0.33 | 0.01 | 0.00 | 0.16 | 2.8 | 23 | 14.1 | 2.2 | 43.9 | 4.5 |
| Hoga Kusten (exponerad kust) | exposed coast | 0.58 | 0.02 | 0.22 | 0.03 | 0.3 | 16 | 17.5 | 5.8 | 71.1 | 6.9 |
| Harjedalen fjall (Funasdalen) | mountain region | 0.70 | 0.10 | 0.15 | 0.03 | 0.1 | 568 | 15.7 | 6.8 | 73.9 | 6.4 |
| Kalixalvens flodslatt | floodplain / far north | 0.47 | 0.09 | 0.14 | 0.16 | 0.4 | 14 | 15.3 | 0.0 | 67.3 | 5.2 |
