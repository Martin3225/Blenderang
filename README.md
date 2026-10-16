# Blender Bridge

Rozmisťování objektů Godot scény v Blenderu a zpět. Přenáší se jen identity
a transformace, nikdy geometrie — ta zůstává v `.glb` (pro hru) a volitelně
v `.blend` (zdroj pro úpravy).

Cíl: Godot 4.7, Blender 5.2, priorita Windows.

```
addons/blender_bridge/   Godot editor plugin
tools/blender_bridge/    Blender extension
```

---

## Pro tým: co se mění

**Kdo nepoužívá Blender, nemusí dělat nic.**

- Hra dál používá jen `.glb` / `.fbx`. Projekt jde otevřít bez Blenderu.
- `project.godot` má `filesystem/import/blender/enabled=false`, takže Godot
  `.blend` soubory ignoruje, ať leží kdekoli. **Nezapínat** — jinak začne
  projekt na strojích bez Blenderu hlásit chyby.
- Scény se mění jen o metadatum `bb_id` na nodech, které jdou z Blenderu
  posouvat.

---

## Instalace

### Godot

Zkopíruj `addons/blender_bridge/` do projektu a zapni v
`Project ▸ Project Settings ▸ Plugins`.

V `Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸ Blender Path` nastav cestu
k Blenderu. Je to stejné nastavení, které Godot používá pro import `.blend`,
takže ho možná už máš.

| odkud | cesta |
|---|---|
| Windows, instalátor | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` |
| Windows, Steam | `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe` |
| Linux, balíček / AUR | `/usr/bin/blender` |
| Linux, Steam | `~/.local/share/Steam/steamapps/common/Blender/blender` |
| Linux, flatpak | `/var/lib/flatpak/exports/bin/org.blender.Blender` |

### Blender

Rozšíření se připojí odkazem z repa, ať se aktualizuje s `git pull`.

**Windows** (příkazová řádka jako správce):

```
mklink /J "%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\blender_bridge" "C:\cesta\k\repu\tools\blender_bridge"
```

**Linux:**

```sh
# balíček, AUR, Steam
ln -sfn "$PWD/tools/blender_bridge" ~/.config/blender/5.2/extensions/user_default/blender_bridge
# flatpak (má vlastní XDG_CONFIG_HOME)
ln -sfn "$PWD/tools/blender_bridge" ~/.var/app/org.blender.Blender/config/blender/5.2/extensions/user_default/blender_bridge
```

Pak v Blenderu `Edit ▸ Preferences ▸ Add-ons ▸ ⌄ ▸ Refresh Local` a zaškrtni
**Blender Bridge**. Jednou, napořád.

Bez odkazu: `blender --command extension build --source-dir tools/blender_bridge`
a zip přes `Install from Disk`.

---

## Použití

Jeden klik na každé straně.

```
Godot    Project ▸ Tools ▸ Blender Bridge ▸ Otevřít scénu v Blenderu
Blender  N ▸ Bridge ▸ Odeslat do Godotu
```

**Otevřít scénu v Blenderu** udělá všechno potřebné sám: při prvním použití
označí art instance (`.glb/.fbx`), uloží scénu, zapíše manifest a spustí
Blender, který si layout postaví bez dalšího klikání.

**Odeslat do Godotu** zapíše transformace zpátky. Godot si změnu všimne do
sekundy a načte ji do otevřené scény jako jednu undo akci — `Ctrl+Z` ji vrátí.

V Blenderu vidíš:

- `BB_Layout` — objekty, se kterými můžeš hýbat, duplikovat (`Shift+D`) a mazat.
- `BB_Locked` — drátěné krabice pro všechno ostatní ze scény: hráč, terén,
  světla, spawnpointy. Nejdou vybrat; jsou tu kvůli kontextu.
- `BB_Sources` — geometrie, na kterou instance ukazují. Skrytá; zobrazí se
  tlačítkem **Zobrazit zdroje**.

Objekty bez `bb_id` addon ignoruje, takže si v Blenderu můžeš dělat pomocnou
geometrii, aniž by skončila ve hře.

### Kdo smí s čím hýbat

Blender zapisuje **jen do nodů s metadatem `bb_id`**. To, že je něco instance
scény, nestačí — `Player` je taky instance a zůstává zamčený. Hromadné
označování vynechává vnitřnosti cizích instancí a cokoli pod fyzikálním
tělesem (to jsou gameplay celky).

Ručně: `… ▸ Pokročilé ▸ Označit výběr / Zrušit označení`. Node s metadatem
`bb_pinned` import přeskočí — pro objekt doladěný v Godotu.

---

## Zdroje geometrie

Zdrojový `.blend` leží **vedle** assetu se stejným názvem:

```
scenes/demo_scene/zviretice_zamek_whitebox/zviretice.glb     ← ve hře
scenes/demo_scene/zviretice_zamek_whitebox/zviretice.blend   ← zdroj
```

Když to nesedí, zapíše se přesná cesta do `<asset>.bbsrc` vedle assetu — jeden
řádek, cesta relativně ke kořeni repa. Vytvoří ho
`… ▸ Pokročilé ▸ Vybrat zdrojový .blend pro výběr…` v Godotu nebo
*Vyrobit zdroj z .glb* v Blenderu. Centrální index záměrně neexistuje, byl by
to zdroj merge konfliktů.

| tier | geometrie | v Blenderu |
|---|---|---|
| `none` | jen `.glb` | model se naimportuje jako náhled; posouvat jde, úpravy se neuloží |
| `library` | vlastní `.blend` vedle assetu | nalinkovaný; **Upravit zdroj** otevře jeho soubor |
| `local` | v layout souboru scény | upravuje se přímo |

### Z náhledu upravitelný model

**Vyrobit zdroj z .glb** na vybraném objektu:

- **Samostatný `.blend`** — kolekce se zapíše vedle assetu a hned se
  nalinkuje zpátky. Tier `library`.
- **Do layoutu scény** — geometrie zůstane v layoutu, zapíše se `.bbsrc`.
  Tier `local`. Layout musí být uložený, jinak by ho Godot nenašel.

Pak **Nastavit glTF export**, aby se `.glb` při uložení zdroje regeneroval.
Převod přes `.glb` zachová meshe, UV a základní materiály, ne shader node
setupy ani modifikátory — dělá se jednou.

---

## Manifest

`.pipeline/<scéna>.json` (+ `.last.json`, snímek pro diff). Adresář má
`.gdignore`.

```json
{
  "format": 1,
  "coord_system": "godot_y_up",
  "scene": "res://scenes/demo_scene.tscn",
  "layout_blend": "scenes/demo_scene.blend",
  "nodes": [
    { "bb_id": "4a7f…", "owner": "blender", "name": "Zviretice",
      "path": "NavigationRegion3D/Zviretice", "parent": "NavigationRegion3D",
      "src": "res://scenes/demo_scene/zviretice_zamek_whitebox/zviretice.glb",
      "tier": "library",
      "src_blend": "scenes/demo_scene/zviretice_zamek_whitebox/zviretice.blend",
      "xform": [bx,by,bz, cx,cy,cz, dx,dy,dz, ox,oy,oz] },
    { "owner": "godot", "name": "Terrain3D", "kind": "terrain",
      "xform": [...], "bounds": { "position": [...], "size": [...] } }
  ]
}
```

`xform` je world transform vůči kořeni scény (tři sloupce báze, pak origin)
v Godot osách. Převod do Blenderu (Z nahoru) dělá výhradně addon. Import zpět
přepočítá na lokální transformaci pod rodičem.

---

## Testováno

Na reálné scéně (Terrain3D, ProtonScatter, 28 nodů), Godot 4.7.2 a Blender 5.2.

**Godot → Blender jedním klikem.** Přesně ten Python, který plugin předává
Blenderu, spuštěný v Blenderu 5.2: scéna se pojmenuje podle manifestu, startup
kostka zmizí, layout má 3 assety a 14 zamčených proxy, importér po sobě
nenechá prázdné kolekce. **8/8.**

**Blender → Godot automaticky.** Živý Godot editor se scénou otevřenou,
manifest změněný zvenku: plugin do sekundy vypsal
`z Blenderu přesunuto 1 … (Ctrl+Z vrátí)`. Manifest z dřívějška se při
startu editoru naslepo nenačetl.

**Rozšíření** se zapne přes `bl_ext.user_default`, panel a všechny operátory
se zaregistrují, tlačítko se jmenuje *Odeslat do Godotu*. **14/14.**

**Round-trip layoutu.** Převod Y-up → Z-up, round-trip bez úprav nic nemění
a Godot-owned položky zůstanou bajt po bajtu stejné, duplikace (která kopíruje
i `bb_id`) dostane nové id, smazání se propíše, `pinned` se nepřepíše. **11/11.**

**Náhled a přesun zdroje.** `zviretice.glb` se naimportoval jako 18 objektů,
*samostatný `.blend`* vznikl vedle assetu a nalinkoval se, *do layoutu* zapsal
`.bbsrc`, bez uloženého layoutu operace skončí chybou. Godot pak hlásí
`library` / `local` bez ručního zásahu. **16/16.**

**Import do scény.** Přesun se zapíše jako lokální transformace pod
`NavigationRegion3D`, nový node vznikne pod správným rodičem, smazaný zmizí,
`Player` a `Terrain3D` zůstanou nedotčené, undo vrátí vše. **6/6.**

Netestováno klikáním v GUI obou programů a na Windows.

---

## Úvaha: zrušit `.blend` pro celou scénu

Zatím neimplementováno. Layout scény (`scenes/<scéna>.blend`) dnes slouží jen
dvěma věcem: tieru `local` a uložení rozpracovaného stavu. Obojí jde jinak.

**Pro zrušení**

- Pravdou o rozmístění je vždycky `.tscn`. Blender se pokaždé postaví
  z manifestu, nemůže se rozejít s Godotem a nic se nemusí řešit při
  `git pull`.
- Žádný binární soubor na scénu, který může držet jen jeden člověk.
- O jeden krok míň: nic se neukládá, Blender je jen editor.

**Proti**

- Zmizí tier `local`. Každý upravitelný model by měl vlastní `.blend`
  vedle `.glb` — to je ale stejně čistší.
- Při úpravě modelu v jeho vlastním `.blend` chybí okolí: terén, ostatní
  modely. Řešení je při **Upravit zdroj** do otevřeného souboru dočasně
  nalinkovat kontext ze scény jako zamčenou referenci a před uložením ho
  zase odebrat. Zdroj zůstane čistý, kontext bude vidět.
- Věci, které v `.tscn` nemají obdobu — referenční obrázky, pomocné křivky,
  a hlavně **animace cutscén** — by potřebovaly vlastní soubor. Cutscéna
  je ale stejně samostatný asset (`cutscene_01.blend` → `.glb` s akcemi),
  ne vlastnost layoutu.

**Doporučení:** zrušit. Layout je přechodný pohled na `.tscn`, zdroje jsou
jen per-asset `.blend`, cutscény per-cutscéna `.blend`. Kontext při úpravě
modelu řeší dočasný link scény.

---

## Co zbývá

- Terrain reference: `Terrain3D ▸ Bake ArrayMesh` → decimovaný mesh jako
  zamčená podlaha v Blenderu (dnes je terén jen krabice z `bounds`).
- Rozhodnout o zrušení layout `.blend` (viz výše).
- Volitelně MultiMesh a live-link transformací přes socket.
