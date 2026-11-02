# Niezapominajka

Przypominajka ważnych terminów w firmie. Wolne oprogramowanie na licencji **GNU AGPL v3.0**.

Strona projektu: https://github.com/maksiu0284/niezapominajka
Twórca: Maksymilian Staszewski, maksymilianstaszewski@gmail.com

Program pilnuje terminów w czterech obszarach:

- pracownicy: badania, umowy, ubezpieczenia, szkolenia, uprawnienia;
- pojazdy: OC/AC, przeglądy, serwisy;
- maszyny produkcyjne: serwisy, przeglądy, UDT;
- sprawy firmy: płatności, podatki, ZUS, licencje.

Program działa na jednym komputerze w firmie (Windows albo Linux), który pełni rolę serwera. Na tym komputerze i na telefonach w sieci firmowej otwierasz go w przeglądarce. Na telefonie możesz go też dodać do ekranu głównego, wtedy działa jak aplikacja.

## Pobieranie

Gotowe pliki są na stronie [Releases](https://github.com/maksiu0284/niezapominajka/releases):

| Plik | Dla kogo |
|---|---|
| `Niezapominajka-1.0.1-instalator.exe` | Windows 10/11, zalecany. Dodaje skrót, autostart i regułę zapory |
| `Niezapominajka-1.0.1-przenosna.exe` | Windows bez instalacji, np. do testów albo na pendrive |
| `Niezapominajka-1.0.1-x86_64.AppImage` | Linux z pulpitem (Ubuntu, Debian, Mint, Fedora) |
| `niezapominajka-1.0.1-linux-serwer.tar.gz` | Linux bez pulpitu: serwer z usługą systemd |
| kod źródłowy | dowolny system z Pythonem 3.10 lub nowszym |

Pliki exe nie mają podpisu cyfrowego. Przy pierwszym uruchomieniu Windows SmartScreen może pokazać ostrzeżenie „System Windows ochronił ten komputer”. Kliknij wtedy „Więcej informacji”, a potem „Uruchom mimo to”.

## Instalacja

### Windows – instalator

1. Uruchom `Niezapominajka-1.0.1-instalator.exe`. Instalator wymaga uprawnień administratora.
2. Zaznacz opcje:
   - skrót na pulpicie;
   - uruchamianie po zalogowaniu (zalecane na komputerze-serwerze);
   - zgoda zapory, żeby telefony mogły się połączyć.
3. Po instalacji program działa w tle. Jego ikona jest w zasobniku obok zegara. Menu ikony ma pozycje:
   - Otwórz;
   - Adres dla telefonu;
   - Folder danych;
   - Pomoc;
   - Zakończ.

Program instaluje się w `C:\Program Files\Niezapominajka`, a dane trzyma w `C:\ProgramData\Niezapominajka`. Odinstalowanie nie usuwa danych.

### Windows – wersja przenośna

Skopiuj `Niezapominajka-1.0.1-przenosna.exe` do wybranego folderu, np. `C:\Niezapominajka`, i uruchom. Dane powstaną w podfolderze `dane` obok pliku. Jeśli telefony mają się łączyć, dodaj ręcznie regułę zapory (zob. „Zapora sieciowa”).

### Linux – AppImage

```bash
chmod +x Niezapominajka-1.0.1-x86_64.AppImage
./Niezapominajka-1.0.1-x86_64.AppImage
```

Otworzy się małe okno z adresem programu i przyciskami, a w przeglądarce otworzy się Niezapominajka. Zamknięcie okna zatrzymuje program. Dane są w `~/.local/share/niezapominajka`.

Jeśli system zgłasza brak FUSE, zainstaluj `libfuse2` (Ubuntu 22.04: `sudo apt install libfuse2`; Ubuntu 24.04 i nowsze: `sudo apt install libfuse2t64`). Możesz też uruchomić program bez FUSE:

```bash
./Niezapominajka-1.0.1-x86_64.AppImage --appimage-extract-and-run
```

### Linux – serwer (bez pulpitu)

Paczka zawiera własnego Pythona, więc niczego nie trzeba doinstalowywać.

```bash
tar -xzf niezapominajka-1.0.1-linux-serwer.tar.gz
cd niezapominajka-1.0.1-linux-serwer
sudo ./install.sh            # albo: sudo ./install.sh --port 8080
```

Skrypt instaluje program w `/opt/niezapominajka`, a dane trzyma w `/var/lib/niezapominajka`. Tworzy też użytkownika systemowego `niezapominajka`, usługę `niezapominajka.service` i, jeśli działa ufw, regułę zapory.

| Czynność | Polecenie |
|---|---|
| stan | `systemctl status niezapominajka` |
| dziennik | `journalctl -u niezapominajka -f` |
| restart | `sudo systemctl restart niezapominajka` |
| aktualizacja | rozpakuj nowszą paczkę i uruchom jej `sudo ./install.sh` (dane zostają) |
| odinstalowanie | `sudo /opt/niezapominajka/uninstall.sh` (dane zostają; `--usun-dane` usuwa także dane) |

### Ze źródeł

Windows: uruchom `start.bat`. Linux: uruchom `./start.sh`, a wcześniej `sudo apt install python3 python3-venv`. Za pierwszym razem skrypt tworzy środowisko `.venv` i pobiera biblioteki.

Opcje uruchomienia, takie same dla exe, AppImage i `run.py`:

| Opcja | Znaczenie |
|---|---|
| `--port 8080` | inny port (domyślnie 8000) |
| `--host 127.0.0.1` | dostęp tylko z tego komputera (domyślnie cała sieć firmowa) |
| `--dane ŚCIEŻKA` | inny folder danych |
| `--serwer` | bez okna i ikony, np. jako usługa |
| `--okno` | wymusza tryb okienkowy przy uruchomieniu ze źródeł |
| `--bez-przegladarki` | nie otwiera przeglądarki po starcie |
| `--wersja` | pokazuje wersję |

Te same ustawienia działają przez zmienne środowiskowe `NIEZAPOMINAJKA_PORT`, `NIEZAPOMINAJKA_HOST` i `NIEZAPOMINAJKA_DANE`.

## Pierwsze uruchomienie – kreator

1. Podaj nazwę firmy i ustawienia przypomnień:
   - ile dni wcześniej przypominać (domyślnie 30);
   - od ilu dni termin jest pilny (domyślnie 7).
2. Załóż konto głównego właściciela. Hasło musi:
   - mieć co najmniej 12 znaków;
   - zawierać małą i wielką literę, cyfrę oraz znak specjalny;
   - nie zawierać loginu.
3. **Kod odzyskiwania** jest pokazywany tylko raz. Wydrukuj go albo zapisz i schowaj. Pozwala ustawić nowe hasło właściciela przez link na stronie logowania.

Program nie ma domyślnego konta ani hasła.

## Telefon

1. Telefon musi być w tej samej sieci Wi-Fi co komputer z programem.
2. Otwórz adres z sieci firmowej, np. `http://192.168.1.20:8000`. Adres znajdziesz:
   - w Panelu właściciela;
   - w menu ikony w zasobniku (Windows);
   - w oknie programu (Linux).
3. Z menu przeglądarki wybierz „Dodaj do ekranu głównego”. W Chrome na Androidzie jest w menu ⋮, w Safari na iPhone pod przyciskiem Udostępnij.

## Role i uprawnienia

- **Właściciel** widzi i zmienia wszystko. W panelu właściciela zarządza:
  - użytkownikami;
  - rodzajami spraw i własnymi polami;
  - ustawieniami i powiadomieniami;
  - dostępem zdalnym, importem i kopiami.

  Przegląda też dziennik zdarzeń: kto, kiedy i co zmienił, z wartością przed i po. Właścicieli może być kilku. Główny jest chroniony przed usunięciem.
- **Użytkownik** ma uprawnienia osobno dla każdego modułu: podgląd, dodawanie, edycja, usuwanie i powiadamianie. Konto może być powiązane z pracownikiem. Użytkownik widzi wtedy swoje terminy i te, za które odpowiada.
- Po 5 błędnych logowaniach konto jest blokowane na 15 minut. Hasło tymczasowe nadane przez właściciela trzeba zmienić przy logowaniu.

## Powiadomienia

### Ręczne – SMS i e-mail z telefonu

Przy terminie naciśnij przycisk powiadomienia. Otworzy się okno z gotową treścią z szablonu, który ustawiasz w Ustawieniach.

- „Otwórz SMS” otwiera aplikację wiadomości z numerem i treścią. Wysyłkę zatwierdzasz sam.
- „Otwórz e-mail” otwiera program pocztowy.
- „Kopiuj” kopiuje treść do schowka. Przydaje się, gdy telefon otworzy pustą wiadomość, bo niektóre aplikacje SMS ignorują treść w linku.

Każde użycie trafia do dziennika zdarzeń.

### Automatyczne – Panel właściciela → Powiadomienia

Program raz dziennie, o ustawionej godzinie, wysyła wiadomość osobie odpowiedzialnej, gdy termin jest:

- wkrótce;
- pilny;
- po terminie (wtedy powtarza co ustawioną liczbę dni).

Użytkownicy mogą też zamówić w profilu codzienne zestawienie. Ta sama wiadomość nie jest wysyłana dwa razy. Komputer z programem musi być włączony. Jeśli był wyłączony, wysyłka nastąpi po uruchomieniu.

**E-mail przez firmową skrzynkę.** Wpisz dane serwera SMTP od dostawcy poczty: serwer, port, szyfrowanie, login, hasło i adres nadawcy.

**E-mail przez Gmail:**

1. Na koncie Google włącz weryfikację dwuetapową.
2. W ustawieniach konta Google, w sekcji „Hasła do aplikacji”, utwórz hasło dla Niezapominajki.
3. Wpisz w programie:
   - serwer `smtp.gmail.com`, port `587`, szyfrowanie STARTTLS;
   - login: pełny adres Gmail;
   - hasło: 16-znakowe hasło aplikacji, nie zwykłe hasło konta.

**SMS przez SMSAPI (usługa płatna):**

1. Załóż konto na smsapi.pl.
2. W panelu SMSAPI wygeneruj token API OAuth z uprawnieniem do wysyłki SMS.
3. Wklej token w programie. Opcjonalnie wpisz nazwę nadawcy zarejestrowaną w SMSAPI.

Tryb testowy przyjmuje wiadomości, ale ich nie wysyła i nie pobiera opłat. Przycisk „Sprawdź token i stan konta SMSAPI” pokazuje stan punktów.

**SMS przez telefon z Androidem (SMS Gateway for Android).** SMS-y kosztują według taryfy karty SIM w telefonie.

1. Zainstaluj w telefonie aplikację „SMS Gateway for Android” ze strony https://sms-gate.app.
2. Wybierz tryb:
   - **lokalny**: telefon w sieci firmowej. W aplikacji włącz „Local server”. W programie wpisz adres telefonu, np. `http://192.168.1.50:8080`, oraz login i hasło pokazane w aplikacji. Telefon powinien mieć stały adres IP, który ustawisz w routerze.
   - **chmurowy**: telefon może być w dowolnej sieci. W aplikacji włącz „Cloud server” i wpisz w programie login i hasło z aplikacji.
3. Telefon musi być włączony i mieć połączenie z siecią. Wyłącz dla aplikacji oszczędzanie baterii.

Po zapisaniu ustawień użyj sekcji „Test wysyłki”. Dziennik wysyłki pokazuje ostatnie 100 wiadomości i ewentualne błędy.

## Dostęp zdalny – Panel właściciela → Dostęp zdalny

Właściciel wybiera jeden z trybów:

- **wyłączony**: tylko sieć firmowa (domyślnie);
- **Tailscale**: zalecany. Prywatna sieć dla Twoich urządzeń, adres `https://komputer.nazwa-sieci.ts.net`, bez otwierania portów w routerze. Zainstaluj Tailscale na serwerze i na telefonach, zaloguj się tym samym kontem i naciśnij w programie „Udostępnij przez Tailscale”;
- **Cloudflare Tunnel**: dostęp z dowolnego miejsca pod własną domeną, z HTTPS od Cloudflare. Instrukcja krok po kroku jest w panelu;
- **własny serwer pośredniczący**: np. Caddy lub nginx z certyfikatem, przekierowujący na `http://127.0.0.1:8000`.

Nie przekierowuj portu 8000 z routera bez HTTPS. Pełny adres zdalny wpisz w polu „Adres publiczny”. Program użyje go w adresach subskrypcji kalendarza.

## Logowanie dwuetapowe (2FA)

Włączasz je w Panelu właściciela → Ustawienia → Bezpieczeństwo i aktualizacje. Po włączeniu:

- jest obowiązkowe dla właścicieli: każdy właściciel ustawia kod przy najbliższym logowaniu;
- jest dobrowolne dla użytkowników: użytkownik włącza je sam w swoim profilu.

Kody generuje aplikacja w telefonie, np. Google Authenticator, Microsoft Authenticator, Aegis lub 2FAS. Konfigurujesz ją w profilu przez zeskanowanie kodu QR.

Zgubiony telefon:

- inny właściciel może wyłączyć 2FA na tym koncie, w karcie użytkownika;
- główny właściciel może też użyć kodu odzyskiwania z kreatora.

## Kalendarz w telefonie (ICS)

W profilu znajdziesz prywatny adres kalendarza. Dodaj go jako subskrypcję w Kalendarzu Google, Outlooku albo w iPhone (Ustawienia → Kalendarz → Konta → Dodaj subskrypcję). Kalendarz pokazuje terminy, które użytkownik może oglądać. Telefon sam pobiera zmiany, zwykle co kilka godzin. Gdy adres wycieknie, naciśnij „Nowy adres”. Na Pulpicie przycisk „Kalendarz” pobiera jednorazowy plik `.ics`.

Do subskrypcji spoza sieci firmowej potrzebny jest dostęp zdalny, np. przez Tailscale na tym samym telefonie.

## Import z Excela – Panel właściciela → Import

1. Pobierz wzór `niezapominajka-wzor-importu.xlsx`. Ma arkusze Instrukcja, Pracownicy, Pojazdy, Maszyny i Terminy.
2. Uzupełnij go i wczytaj.
3. Program pokaże podgląd: co doda, co pominie (np. duplikaty) i jakie są błędy.
4. Dopiero „Zatwierdź import” zapisuje dane. Przed zapisem program sam robi kopię zapasową.

## Aktualizacje

Program raz dziennie sprawdza na GitHubie, czy jest nowsza wersja, i pokazuje właścicielom pasek z linkiem. Sprawdzanie wyłączysz w Panelu właściciela → Ustawienia → Bezpieczeństwo i aktualizacje. Program wysyła tylko zapytanie o numer wersji, bez danych firmy. Aktualizacja polega na zainstalowaniu nowszej wersji na starą. Dane zostają.

## Dane programu i kopie zapasowe

| Plik / folder | Zawartość |
|---|---|
| `niezapominajka.db` | baza danych (SQLite) |
| `zalaczniki/` | pliki i zdjęcia dodane do terminów (do 25 MB na plik) |
| `kopie/` | kopie zapasowe ZIP (14 automatycznych + ręczne) |
| `klucz_sesji.txt` | klucz sesji logowania, nie udostępniaj go |
| `niezapominajka.log` | dziennik techniczny wersji okienkowej |

Gdzie jest folder danych:

| Wersja | Folder |
|---|---|
| instalator Windows | `C:\ProgramData\Niezapominajka` |
| exe przenośny | `dane` obok pliku exe |
| AppImage | `~/.local/share/niezapominajka` |
| serwer Linux | `/var/lib/niezapominajka` |
| źródła | `dane` obok `run.py` |

Program robi kopię raz na dobę. Właściciel może też zrobić i pobrać kopię w Panelu właściciela → Kopie zapasowe. Co jakiś czas skopiuj pliki z `kopie/` na inny nośnik.

**Uwaga:** baza zawiera hasło do poczty, token SMSAPI i hasło bramki SMS. Kopie zapasowe zawierają je również. Trzymaj kopie w bezpiecznym miejscu i nie wysyłaj ich nikomu.

**Przywracanie kopii:**

1. Zatrzymaj program.
2. Przenieś obecny folder danych w bezpieczne miejsce.
3. Utwórz pusty folder danych i rozpakuj do niego ZIP. Pojawią się `niezapominajka.db` i `zalaczniki/`. Skopiuj też `klucz_sesji.txt` z poprzedniego folderu.
4. Uruchom program.

## Zapora sieciowa

Instalator Windows i `install.sh` ustawiają zaporę same. Ręcznie:

```powershell
# Windows, PowerShell jako administrator
New-NetFirewallRule -DisplayName "Niezapominajka" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Domain
```

```bash
# Linux z ufw
sudo ufw allow 8000/tcp
```

## Dla twórcy – publikacja na GitHubie

### Pierwsze wypchnięcie kodu

Pliki z `.github/workflows/` wymagają tokenu z uprawnieniem `workflow`. Utwórz token na GitHubie:

1. Wejdź w Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token.
2. Zaznacz zakresy `repo` i `workflow`.
3. Token wpisuj zamiast hasła, gdy git o nie poprosi.

```bash
cd niezapominajka
git init -b main
git add .
git commit -m "Niezapominajka 1.0.1"
git remote add origin https://github.com/maksiu0284/niezapominajka.git
git push -u origin main
```

Jeśli repozytorium na GitHubie ma już plik, np. README albo LICENSE, przed `git push` wykonaj `git pull origin main --allow-unrelated-histories`.

### Wydanie wersji

```bash
git tag v1.0.1
git push origin v1.0.1
```

GitHub Actions zbuduje wtedy instalator, wersję przenośną, AppImage i paczkę serwerową. Doda je do strony Releases razem z plikiem `SHA256SUMS.txt`. Przy kolejnej wersji zmień numer w trzech miejscach:

- `app/config.py` (`APP_VERSION`);
- `packaging/windows/installer.iss`;
- `packaging/windows/version.txt`.

Dopisz też zmiany do `CHANGELOG.md`.

### Budowa lokalna

- Linux: `packaging/linux/build_linux.sh`. Wyniki trafiają do `dist/`.
- Windows: `packaging\windows\build_windows.bat`. Wymaga Pythona 3.12 i Inno Setup 6. Wyniki trafiają do `dist-win\`.

### Wsparcie przez GitHub Sponsors

Plik `.github/FUNDING.yml` dodaje na stronie repozytorium przycisk „Sponsor”. Program w karcie „O programie” prowadzi do https://github.com/sponsors/maksiu0284. Link zacznie działać po włączeniu profilu Sponsors:

1. Wejdź na https://github.com/sponsors i wybierz „Get started” przy swoim koncie osobistym.
2. Uzupełnij profil, progi wsparcia i dane rozliczeniowe (Stripe).
3. Poczekaj na akceptację przez GitHub.

## Licencja

Copyright © 2026 Maksymilian Staszewski

Niezapominajka jest wolnym oprogramowaniem: możesz ją rozpowszechniać i zmieniać na warunkach GNU Affero General Public License w wersji 3 lub dowolnej późniejszej. Program jest dostarczany bez jakiejkolwiek gwarancji. Pełny tekst licencji jest w pliku `LICENSE`. Jeśli udostępniasz zmienioną wersję innym przez sieć, musisz udostępnić im także jej kod źródłowy.
