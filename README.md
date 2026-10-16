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

**Godot → Blender**, kterékoli z:

- tlačítko **Blender** v liště 3D editoru (vedle *Transform*, *View*),
- pravé tlačítko na **tabu scény** ▸ *Otevřít v Blenderu*,
- pravé tlačítko na **`.tscn` ve FileSystemu** ▸ *Otevřít v Blenderu* — scénu
  nejdřív otevře, když není aktivní.

Při prvním použití označí art instance (`.glb/.fbx`), pak uloží scénu, zapíše
manifest a spustí Blender, který si scénu postaví bez dalšího klikání.

**Blender → Godot:** velké tlačítko **Odeslat do Godotu** v `N ▸ Bridge`.
Godot si změnu všimne do sekundy a načte ji do otevřené scény jako jednu undo
akci — `Ctrl+Z` ve scéně ji vrátí.

Scéna v Blenderu **nemá vlastní `.blend` a nic se neukládá**. Pravdou
o rozmístění je vždycky `.tscn`; Blender je jen editor nad ní a pokaždé se
postaví znovu z manifestu. Nemůže se tak rozejít s Godotem a `git pull` nic
nerozbije.

Panel `N ▸ Bridge`:

- **Odeslat do Godotu**
- **Znovu načíst z Godotu** — postaví scénu z posledního manifestu (zahodí
  neodeslané změny); hodí se i po změnách v Godotu.
- **Modely** — seznam všech modelů scény s hledáním (jméno, cesta v Godotu
  i název assetu, víc slov = všechna musí sedět). Klik na jméno model vybere
  a zaměří.
  Vedle je **Upravit** (model má zdrojový `.blend`), nebo **Vyrobit zdroj**
  (model je zatím jen náhled z `.glb`).
- **Detail** — o vybraném objektu: u modelu node v Godotu, rodič, asset,
  zdrojový `.blend` (nebo kam se vyrobí) a id, plus tlačítka **Upravit** /
  **Vyrobit zdroj**, **Vybrat zdroj…** a **Zrušit výběr zdroje**; u objektu
  z Godotu, ke kterému nodu patří; u ostatního, že je to pomocný objekt,
  který se neposílá.
- Pokud se něco nepodařilo načíst (vadný asset, vadný kontext), panel to
  vypíše červeně. Scéna se i tak dostaví — vadný model zůstane jako osa na
  svém místě, místo vadného kontextu jsou obálky.

V outlineru:

- `BB_Layout` — modely, se kterými můžeš hýbat, otáčet je, duplikovat
  (`Shift+D`) a mazat. Každý je vidět jednou, na svém místě. Model, který je
  v Godotu dítětem jiného modelu (výstroj na `armature_f`), je v Blenderu jeho
  potomkem: posun rodiče posune i děti. Když v Blenderu smažeš rodiče a děti
  necháš, v Godotu se přesunou pod nejbližšího předka.
- `BB_Locked` — skutečná geometrie všeho ostatního ze scény: postavy, budovy,
  terén (z Terrain3D, vrchol každých 16 m, s upečenou barvou), spawnpointy
  a markery jako osy
  velké 1 m, světla. Jde vybrat
  a zaměřit (`numpad .`), ale ne posunout — změny by se do Godotu stejně
  nepropsaly. Tráva a stromy z MultiMeshe (ProtonScatter) se nepřenáší.

Objekty bez `bb_id` se do Godotu neposílají — pomocná geometrie ve hře
neskončí. Protože se scéna neukládá, při dalším otevření z Godotu zmizí.

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

Když to nesedí (jeden `.blend` s víc modely, zdroj jinde), vybere se zdroj
ručně: v Blenderu **Detail ▸ Vybrat zdroj…** (prohlížeč souborů začne vedle
assetu), v Godotu `Project ▸ Tools ▸ Blender Bridge ▸ Vybrat zdrojový .blend
pro výběr…`. Platí pro všechny instance assetu.

| kde leží vybraný `.blend` | kam se uloží | kdo ho vidí |
|---|---|---|
| v projektu | `<asset>.bbsrc` vedle assetu (cesta relativně ke kořeni) | celý tým přes git |
| mimo projekt | `.pipeline/local/sources.json` (absolutní cesta) | **jen ty** |

Zdroj mimo projekt je pro případ, kdy zdrojáky nemá každý. Blender i Godot
na to po výběru upozorní a panel Detail to u modelu ukazuje červeně —
ostatní ho neuvidí a model upravit nemůžou, uvidí dál jen `.glb`.
`.pipeline/local/` má vlastní `.gitignore` s `*`, takže se nikdy necommitne
a do týmového `.gitignore` není potřeba sahat.

Pořadí: osobní výběr → `.bbsrc` → `.blend` vedle assetu. **Zrušit výběr
zdroje** zruší nejdřív osobní výběr, pak sdílený. Centrální index záměrně
neexistuje, byl by to zdroj merge konfliktů.

| tier | geometrie | v Blenderu |
|---|---|---|
| `none` | jen `.glb` | naimportuje se jako náhled; posouvat jde, úpravy tvaru se neuloží |
| `library` | vlastní `.blend` vedle assetu | nalinkovaný; **Upravit model** otevře jeho soubor |

### Z náhledu upravitelný model

**Vyrobit zdroj** zapíše model do nového `.blend` vedle assetu i s nastaveným
exportem do `.glb` a hned ho nalinkuje zpátky — u všech instancí téhož assetu.
Převod přes `.glb` zachová meshe, UV, armaturu a základní materiály, ne shader
node setupy ani modifikátory — dělá se jednou. Existující `.blend` se nikdy
nepřepíše.

### Úprava modelu

**Upravit** u modelu:

1. odešle rozpracované přesuny do Godotu, ať se nic neztratí,
2. otevře zdrojový `.blend` modelu,
3. kolem modelu postaví **zamčený kontext ze scény** (`BB_Context`) —
   skutečnou geometrii z Godotu i ostatní modely — posunutý tak, jako by
   model stál na svém místě ve scéně. Další výskyty téhož modelu ukazují na
   upravovanou kolekci, takže úpravy jsou vidět na všech místech naráz.

`Ctrl+S` model uloží **a přegeneruje `.glb`**; Godot ho sám reimportuje.
Kontext se před každým uložením odebere a po něm vrátí, do zdrojového souboru
se nikdy nezapíše.

**Uložit a zpět do scény** postaví scénu znovu z manifestu, už s novým modelem.

---

## Manifest

`.pipeline/<scéna>.json` (+ `.last.json`, snímek pro diff). Adresář má
`.gdignore`.

```json
{
  "format": 1,
  "coord_system": "godot_y_up",
  "context_glb": ".pipeline/demo_scene.context.glb",
  "nodes": [
    { "bb_id": "4a7f…", "owner": "blender", "name": "Zviretice",
      "path": "NavigationRegion3D/Zviretice", "parent": "NavigationRegion3D",
      "src": "res://scenes/demo_scene/zviretice_zamek_whitebox/zviretice.glb",
      "tier": "library",
      "src_blend": "scenes/demo_scene/zviretice_zamek_whitebox/zviretice.blend",
      "xform": [bx,by,bz, cx,cy,cz, dx,dy,dz, ox,oy,oz],
      "bounds": { "position": [...], "size": [...] } },
    { "owner": "godot", "name": "Terrain3D", "kind": "terrain",
      "xform": [...], "bounds": { "position": [...], "size": [...] } }
  ]
}
```

`xform` je world transform vůči kořeni scény (tři sloupce báze, pak origin)
v Godot osách; node s `top_level` (Terrain3D) rodiče ignoruje. Převod do
Blenderu (Z nahoru) dělá výhradně addon. Import zpět přepočítá na lokální
transformaci pod rodičem.

`.context.glb` je skutečná geometrie všeho, co vlastní Godot, a terén upečený
z Terrain3D. `bounds` slouží jako záložní krabice, když `.glb` chybí.

### Materiál terénu

Shader Terrain3D (splatting z texturového pole, control mapa, auto shader podle
sklonu) do Blenderu 1:1 převést nejde. Plugin proto upeče barvu terénu shora:
v každém pixelu průměrná barva textur, které tam control mapa míchá — nebo
auto shader stejným vzorcem jako Terrain3D (`auto_slope`, `auto_height_reduction`,
`auto_base/overlay_texture`) — vynásobená barevnou mapou. Výsledek vypadá jako
plochá satelitní mapa bez osvětlení a makrovariace, na rozmisťování stačí.

Textura má 1024 px na delší straně (u 8 × 4 km terénu 7,5 m/px), pečení trvá
asi 3 s. Ukládá se do `.pipeline/<scéna>.terrain.png` a znovu se počítá, jen
když se změní data terénu, textury nebo parametry auto shaderu.

---

## Testy

```sh
python tests/run_tests.py                      # všechno (165 testů), ~40 s
python tests/run_tests.py --only blender       # jedna sada
python tests/run_tests.py --regen-fixtures     # přegenerovat testovací scény
```

Potřeba: Python 3, Godot 4.7 a Blender 5.2 (na PATH, v `$GODOT`/`$BLENDER`,
nebo `--godot`/`--blender`; flatpak a Steam se najdou samy). Terrain3D si
runner stáhne (zafixovaná verze 1.0.2) do `tests/.cache`. Pro GUI sadu na
Linuxu `Xvfb`.

Všechno běží v `tests/.work`: testovací projekt se zkopíruje a addon se do něj
doplní z repa. Godot i Blender dostanou vlastní konfigurační adresáře, takže
se nedotknou tvých nastavení, a Blender běží s `--factory-startup` bez tvých
addonů.
**Tvého herního projektu se testy nedotknou.**

### Testovací scény

`tests/godot/fixtures/` generuje `fixtures/generate.gd` (scény) a
`tests/fixtures/make_assets.py` (assety). Pokrývají:

| fixture | co testuje |
|---|---|
| `Props/Crate`, `Tower`, `Barrel` (.fbx) | art instance v kontejneru, glTF i FBX |
| `Rotated/InRotated` | rodič otočený o 90° a zvětšený 2× |
| `Rotated/Detached` | `top_level` pod transformovaným rodičem |
| `Player` (.tscn) | gameplay instance — nesmí se označit |
| `Building` + `Decoration` | těleso s meshem, kolizí a vnořenou instancí |
| `Character` (`rig.glb`) | armatura — pomocné tvary kostí importéru |
| `Character/Helmet`, `Character/Socket` | dítě modelu (výstroj) a marker na modelu |
| `Spawn`, `Sun`, `Logic/Floating` | kontext bez meshe, Node mezi Node3D |
| `terrain.tscn` | Terrain3D pod posunutým rodičem, kopec, krabice na vrcholu; tři textury, malovaný písek, kvadrant s auto shaderem, obarvený roh |
| `second.tscn` | otevření neaktivní scény z kontextového menu |

### Use casy a sady

| use case | sada |
|---|---|
| První otevření: označení, uložení scény, manifest, kontext, spuštění Blenderu | editor, godot |
| Tlačítko v liště, kontextové menu tabu i FileSystemu | editor |
| Blender postaví scénu ze startovního Pythonu (i v okně z časovače) | gui, e2e |
| Model je vidět jednou, na místě z Godotu (rotace, měřítko, `top_level`) | blender |
| Skutečná geometrie kontextu, terén, zamčená ale vybratelná | blender, godot |
| Posun, rotace, měřítko → správná lokální transformace v Godotu | blender, godot, e2e |
| Duplikace → nová instance s vlastním id pod správným rodičem | blender, godot, e2e |
| Smazání; pomocné objekty bez `bb_id` se neposílají | blender, godot, e2e |
| `bb_pinned` v Godotu; gameplay nody se nemění | blender, godot, e2e |
| Automatické načtení, Ctrl+Z ve scéně, starý manifest po restartu | editor |
| Vyrobit zdroj: `.blend` vedle assetu s exportem, všechny instance | blender, gui, e2e |
| Upravit model: kontext, Ctrl+S přegeneruje `.glb`, kontext se neuloží | blender, gui |
| `.bbsrc`, zdroj vedle assetu, poškozený zdroj; Vybrat / Zrušit zdroj | godot, blender |
| Zdroj mimo projekt: osobní, neuloží se do repa, upozornění, úprava modelu | godot, blender, gui |
| Děti modelů: hierarchie v Blenderu, posun s rodičem, smazání rodiče | godot, blender, e2e |
| Materiál terénu: control mapa, auto shader, barevná mapa, cache | godot, blender |
| Hledání v seznamu modelů | blender, gui |
| Panel v obou režimech, zaměření pohledu, dohled na terén | gui |

Netestováno na Windows (runner tam GUI sadu přeskočí).

### Co testy našly

Při psaní testů a ostrém použití se ukázalo třináct chyb, všechny opravené
a pokryté testem:

- **Děti modelu (výstroj na `armature_f`) se do Blenderu vůbec nedostaly** —
  manifest bral model jako celek a jeho děti ze scény neprocházel.
- **Dítě posunuté s rodičem se v Godotu posunulo dvakrát** — lokální
  transformace se počítala vůči staré pozici rodiče.

- **Kontext exportovaný z editoru byl prázdný.** glTF export v editoru
  přeskakuje nody bez `owner`; mimo editor ne, proto to headless testy
  nechytily. Editor test teď kontroluje i obsah `.context.glb`.
- **Vadný `.glb` shodil celou stavbu scény** — Blender pak neukázal kontext,
  seznam modelů ani detail.

- **Blender v okně spadl při stavbě scény s armaturou.** Startovní příkaz
  z Godotu běží z časovače bez 3D pohledu a glTF importér si ho u armatur
  vyžaduje. Stavba skončila v půlce — odtud zdvojené modely v počátku.
- **Náhledy modelů byly ve scéně podruhé** (v počátku) a pomocný tvar kostí
  armatury se válel ve scéně (`Icosphere`).
- **Terrain3D dostal posun rodiče**, přestože je `top_level`; při importu
  zpět by se totéž stalo každému `top_level` nodu.
- **Kontext obsahoval interní mesh Terrain3D** (`MouseQuad`) a geometrii
  vnořených jednotek dvakrát.
- **Ctrl+Z ve scéně nevracel import** — akce skončila v globální historii.
- **Export do `.glb` po uložení zdroje fungoval jen náhodou** —
  `libraries.write` neuloží cestu exporteru a `wm.collection_export_all`
  exportuje jen kolekce ve scéně.
- **Vyrobit zdroj přepojil jen jednu instance** — ostatní instance téhož
  `.glb` přišly o geometrii.
- **Odeslání ze skriptu posílalo starou pozici** (nepřepočtená matice).
- **Poškozený `.blend` vedle assetu shodil otevření celé scény.**

---

## Rozhodnutí: scéna nemá `.blend`

Layout scény jako `.blend` byl zrušen. Pravdou o rozmístění je `.tscn`,
Blender je jen editor nad ní.

- Nemůže se rozejít s Godotem, `git pull` nic nerozbije, žádný binární soubor
  na scénu, který může držet jen jeden člověk, o krok méně (nic se neukládá).
- Každý upravitelný model má vlastní `.blend` vedle `.glb`.
- Okolí při úpravě modelu dodává dočasný kontext z manifestu, který se do
  zdroje nikdy neuloží.
- Cutscény budou samostatné soubory (`cutscene_01.blend` → `.glb` s akcemi),
  ne vlastnost layoutu.

---

## Co zbývá

- Úprava heightmapy terénu v Blenderu (rozmyšleno, viz níže).
- Tráva a stromy z MultiMeshe.
- Ověření na Windows.
