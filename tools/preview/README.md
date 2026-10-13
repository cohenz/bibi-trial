# תצוגה מקדימה ובדיקת ניגודיות של התוסף (בלי וורדפרס)

1. נתונים מה־API הציבורי לתיקייה הזו: `guide.json` (`/v2/guide`), `timeline.json` (`/v2/guide/timeline`), `glossary.json` (`/v2/glossary`),
   `docs.json` (`/v2/documents?limit=200`), `hearing.json` (`/v2/hearings/<hr_id>`), `w_yeshua.json` (`/v2/guide/witnesses/<slug>`),
   `ask_after.json` (מערך של שני AnswerEnvelope מ־`POST /v2/ask`).
2. `php render.php` — מרנדר עמודי HTML עם ה־CSS של התוסף **ועם כללי הכפתורים והקישורים של ערכת Astra** (כמו באתר).
3. `npm i && node audit.js [עמודים…]` — כל כפתור וקישור במצב רגיל, ריחוף ופוקוס; מדפיס רק מה שמתחת ל־4.5:1. פלט ריק = תקין.
4. `node shot.js` — צילומי מסך.
