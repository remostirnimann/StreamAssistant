# Terms of use

Stream Assistant (the Home Assistant integration) and the Stream Assistant Bridge are free
software under the [MIT License](../LICENSE). These terms explain what the software is meant
for. They do not restrict the licence; they say where you use it at your own risk.

*[Deutsch weiter unten](#nutzungsbedingungen)*

## Intended use

- The bridge is meant for a **home or office network**: it connects Stream Decks on a
  computer to a Home Assistant instance in the same local network.
- Using the bridge from **outside the local network** is **not intended**: no port
  forwarding of port 5390 on the router, no exposure to the internet. The bridge refuses
  connections from public addresses unless it is started with `--allow-public true`.
  Whoever turns this on, or reaches the bridge in other ways from outside (for example a
  reverse proxy), does so **at their own risk**.
- A VPN into your own network (for example WireGuard or Tailscale) counts as the local
  network.

## Your responsibility

- You decide which Home Assistant actions the keys run (lights, locks, alarm systems,
  heating, garage doors …). Check that a press of the wrong key cannot cause harm, and
  protect sensitive actions in Home Assistant itself (for example with a confirmation or a
  PIN).
- Keep the pairing code to yourself: whoever pairs with the bridge can show images on the
  decks and receives their key presses.
- Keep Home Assistant, the integration and the bridge up to date.

## No warranty, no liability

The software is provided **as is**, without warranty of any kind. It is developed in spare
time and may contain errors. As far as the law allows, the authors are not liable for any
damage that results from installing or using the software, from errors in it, or from its
use outside the intended purpose; the full wording is in the [MIT License](../LICENSE).
You use the software at your own risk.

Stream Assistant is not affiliated with Elgato or Corsair. Elgato and Stream Deck are
trademarks of Corsair Memory, Inc.

---

## Nutzungsbedingungen

Stream Assistant (die Home-Assistant-Integration) und die Stream Assistant Bridge sind
freie Software unter der [MIT-Lizenz](../LICENSE). Diese Bedingungen erklären, wofür die
Software gedacht ist. Sie schränken die Lizenz nicht ein, sondern sagen, wo die Nutzung auf
eigene Gefahr geschieht.

### Bestimmungsgemässer Gebrauch

- Die Bridge ist für ein **Heim- oder Büronetz** gedacht: Sie verbindet Stream Decks an
  einem Computer mit einem Home Assistant im selben lokalen Netz.
- Die Nutzung der Bridge **ausserhalb des lokalen Netzes** ist **nicht vorgesehen**: keine
  Portweiterleitung von Port 5390 im Router, keine Freigabe ins Internet. Die Bridge lehnt
  Verbindungen von öffentlichen Adressen ab, ausser sie wird mit `--allow-public true`
  gestartet. Wer das einschaltet oder die Bridge auf anderem Weg von aussen erreichbar
  macht (zum Beispiel über einen Reverse Proxy), tut das **auf eigene Gefahr**.
- Ein VPN ins eigene Netz (zum Beispiel WireGuard oder Tailscale) gilt als lokales Netz.

### Ihre Verantwortung

- Sie bestimmen, welche Aktionen in Home Assistant die Tasten auslösen (Licht, Schlösser,
  Alarmanlagen, Heizung, Garagentore …). Prüfen Sie, dass ein Druck auf die falsche Taste
  keinen Schaden anrichten kann, und schützen Sie heikle Aktionen in Home Assistant selbst
  (zum Beispiel mit einer Bestätigung oder einem PIN).
- Geben Sie den Kopplungscode nicht weiter: Wer sich mit der Bridge koppelt, kann Bilder
  auf den Decks anzeigen und erhält deren Tastendrücke.
- Halten Sie Home Assistant, die Integration und die Bridge aktuell.

### Keine Gewährleistung, keine Haftung

Die Software wird **so, wie sie ist**, zur Verfügung gestellt, ohne jede Gewährleistung. Sie
wird in der Freizeit entwickelt und kann Fehler enthalten. Soweit gesetzlich zulässig,
haften die Autoren nicht für Schäden, die durch die Installation oder Nutzung der Software,
durch Fehler darin oder durch eine Nutzung ausserhalb des vorgesehenen Zwecks entstehen;
massgebend ist der Wortlaut der [MIT-Lizenz](../LICENSE). Sie nutzen die Software auf
eigene Gefahr.

Stream Assistant steht in keiner Verbindung zu Elgato oder Corsair. Elgato und Stream Deck
sind Marken von Corsair Memory, Inc.
