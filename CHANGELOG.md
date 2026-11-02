# Zmiany

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
