# Zmiany

## 1.0.2 – 2026-11-03

Wydanie z poprawkami bezpieczeństwa. Dane z 1.0.0 i 1.0.1 zostają – baza aktualizuje się sama przy pierwszym uruchomieniu. Po aktualizacji wszyscy muszą zalogować się jeszcze raz.

### Załączniki

- Typ pliku jest ustalany po zawartości (sygnatura), a nie po rozszerzeniu i typie podanym przez przeglądarkę. Plik, którego treść nie pasuje do rozszerzenia, jest odrzucany (np. strona HTML ze skryptem zapisana jako `zdjecie.png`).
- Zablokowane rodzaje plików: HTML, SVG, XML, skrypty i programy.
- W przeglądarce otwierają się tylko zdjęcia i PDF, reszta jest pobierana. Pobierane pliki mają nagłówki `X-Content-Type-Options: nosniff` i `Content-Security-Policy: sandbox`.
- Załączniki dodane we wcześniejszych wersjach są sprawdzane przy starcie; podejrzane są od tej pory tylko pobierane, nigdy wyświetlane.

### Logowanie i sesje

- Sesje przechowywane na serwerze: wylogowanie, zmiana hasła i reset 2FA unieważniają sesję od razu. „Wyloguj wszędzie” w profilu, wylogowanie dowolnego konta przez właściciela w panelu.
- Zamiast blokady konta: rosnące opóźnienie dla adresu, z którego przychodzą błędne hasła (od 6. próby 1, 2, 4… s, najwyżej 15 min). Nikt nie zablokuje cudzego konta.
- Ten sam komunikat i czas odpowiedzi dla nieistniejącego loginu i złego hasła.
- Ciasteczko z flagą Secure przy połączeniu HTTPS (także przez Tailscale, Cloudflare i własny proxy).
- Kod odzyskiwania znika z sesji po wyświetleniu; plik z kodem można pobrać raz, w ciągu 10 minut.
- Kod odzyskiwania nie włącza wyłączonego konta. Wyłączenie konta lub odebranie roli właściciela unieważnia jego kod.
- Login, e-mail, hasło i 2FA głównego właściciela może zmienić tylko on sam.
- Parametr powrotu (`back`) przyjmuje tylko adresy wewnątrz programu.
- Ostrzeżenie o niezaszyfrowanym połączeniu HTTP na stronie logowania (można je ukryć na danym urządzeniu) i w panelu właściciela.

### Pozostałe

- Nagłówki bezpieczeństwa: Content-Security-Policy, X-Frame-Options, Referrer-Policy, nosniff. Skrypty wbudowane w strony przeniesione do plików.
- Strony po zalogowaniu nie są zapisywane w pamięci podręcznej przeglądarki (`Cache-Control: no-store`).
- Eksport do Excela i CSV: tekst zaczynający się od `=`, `+`, `-`, `@` nie jest traktowany jak formuła (także w dzienniku zdarzeń).
- Okno powiadomienia: pełna lista kontaktów tylko dla osób z prawem podglądu pracowników; pozostali widzą osobę odpowiedzialną.
- Ostrzeżenie przy adresie bramki SMS Android zaczynającym się od `http://`.
- Instalator Windows: folder danych dostępny tylko dla Administratorów, SYSTEM i konta instalującego (dawniej modyfikować mogli wszyscy użytkownicy komputera). Dotyczy też istniejącego folderu.
- Wersja przenośna: ostrzeżenie w Pomocy i w panelu o ochronie folderu `dane`.
- Folder danych na Linuksie bez dostępu dla innych użytkowników.
- Przypięte wersje bibliotek. Usunięta zależność itsdangerous i plik `klucz_sesji.txt`.
- Poprawka: ikona lupy nie nachodzi na tekst w polu wyszukiwania.

## 1.0.1 – 2026-11-02

- Poprawka: pasek boczny przewija się, gdy menu nie mieści się w oknie (niskie okno na komputerze, menu na telefonie). Pozycje „Mój profil” i „Wyloguj” są zawsze osiągalne.

## 1.0.0 – 2026-11-02

Pierwsze wydanie pod nazwą Niezapominajka. Program zastępuje „Terminy firmowe” (pas.py, Streamlit) i nie przenosi danych z tamtej wersji.

### Terminy

- Cztery moduły: pracownicy, pojazdy, maszyny i sprawy firmy, wspólnie w jednej liście terminów.
- Rodzaje spraw z domyślnym cyklem.
- Terminy cykliczne: oznaczenie „wykonane” planuje kolejny termin.
- Osoba odpowiedzialna przy każdym terminie.
- Załączniki: pliki biurowe i zdjęcia.
- Własne pola, wyszukiwanie i filtry, eksport do Excela i CSV, druk.
- Import z Excela z podglądem i automatyczną kopią przed zapisem.
- Kalendarz ICS: subskrypcja z prywatnym adresem w profilu oraz eksport do pliku.

### Konta i bezpieczeństwo

- Kreator pierwszego uruchomienia: silne hasło i kod odzyskiwania, bez domyślnego konta.
- Wielu właścicieli. Użytkownicy z uprawnieniami per moduł: podgląd, dodawanie, edycja, usuwanie i powiadamianie.
- Dziennik zdarzeń z wartościami przed i po zmianie.
- Logowanie dwuetapowe (TOTP) jako opcja w panelu: obowiązkowe dla właścicieli, dobrowolne dla użytkowników.
- Blokada konta po 5 błędnych logowaniach. Hasła tymczasowe z wymuszeniem zmiany.

### Powiadomienia

- Ręczne SMS (link `sms:`) i e-mail (`mailto:`) z szablonów. Przycisk „Kopiuj” kopiuje treść.
- Automatyczne powiadomienia raz dziennie:
  - e-mail przez SMTP lub Gmail z hasłem aplikacji;
  - SMS przez SMSAPI;
  - SMS przez telefon z Androidem (SMS Gateway for Android, tryb lokalny lub chmurowy).
- Codzienne zestawienie dla użytkowników. Dziennik wysyłki chroni przed wysłaniem tej samej wiadomości dwa razy.

### Dostęp zdalny

Tryb wybierany w panelu: wyłączony, Tailscale, Cloudflare Tunnel albo własny serwer pośredniczący. Opcjonalnie własny certyfikat HTTPS.

### Wygląd

- Nowa ikona: mózg i kwiat niezapominajki.
- Niebieska kolorystyka i tryb ciemny.
- Interfejs dopasowany do telefonu (PWA).

### Program

- Karty „Pomoc” i „O programie”: licencja AGPL-3.0, twórca, użyte komponenty, wsparcie przez GitHub Sponsors.
- Sprawdzanie aktualizacji na GitHubie (można wyłączyć).
- Kopie zapasowe: automatyczne co dobę (14 najnowszych) i ręczne.

### Wydania

- Windows: instalator (skrót, autostart, reguła zapory) i wersja przenośna z ikoną w zasobniku.
- Linux: AppImage oraz paczka serwerowa z usługą systemd.
