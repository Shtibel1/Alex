"""Generic products: fresh food that every chain sells under its own code.

Produce, meat, poultry and fish are sold by weight with chain-specific item
codes, so barcode matching can't compare them. Each generic product here is a
name pattern; for every store we pick the cheapest matching item and compare
that price (per kg, or per pack for the few per-unit items).

Patterns run against a normalised name (Hebrew/Latin letters, digits and single
spaces, padded with a space on both sides), so " חזה עוף " matches whole words.
A leading "^" anchors to the start of the name, which keeps "רוטב עגבניות" out of
tomatoes and "משקה חלב בננה" out of bananas.
"""

import re
import statistics

# (key, display name, category, unit, match regex, exclude regex or None, extra)
# unit: "kg" -> only items priced per kg; "unit" -> per-unit items, `extra`
# may then require a pack size, e.g. {"qty": 12}.
_KG, _UNIT = "kg", "unit"

CATALOG = [
    # ---- עוף והודו ----
    ("chicken-breast", "חזה עוף טרי", "עוף והודו", _KG, r"^ ?חזה ", r"קפוא|טחון|מעושן|הודו|אווז|בקר|בגריל|מוקפץ|פרוס|שניצל|רצועות|נתחי|צלוי|מתובל|שיפוד|פרימיום", {"must": r"עוף|חזה חצוי"}),
    ("chicken-breast-frozen", "חזה עוף קפוא", "עוף והודו", _KG, r"חזה (עוף )?.*קפוא|קפוא.* חזה עוף", r"טחון|מעושן|הודו|אווז|בקר|שניצל|מתובל|פרוס|צרכני", {"must": r"עוף|חזה"}),
    ("chicken-schnitzel", "שניצל עוף טרי", "עוף והודו", _KG, r"^ ?שניצל (עוף|טרי|חזה|דק)", r"קפוא|הודו|עגל|בקר|תירס|צמחוני|מן הצומח|טבעול|פריך|מטוג|מוכן|אפוי|ציפוי|ביס|תפוא", {"must": r"עוף|טרי|חזה"}),
    ("chicken-whole", "עוף שלם", "עוף והודו", _KG, r"^ ?עוף (שלם|טרי שלם|טרי ארוז שלם)|^ ?עוף טרי $|^ ?עוף שלם", r"קפוא|צלוי|בגריל|ממולא|פרגית|מתובל", None),
    ("chicken-thighs", "ירכיים עוף", "עוף והודו", _KG, r"^ ?(ירכיים|ירך|ירכי) (עוף|שלמות|טרי)", r"קפוא|מתובל|צלוי|הודו|פרגית|נקניק", None),
    ("chicken-legs", "כרעיים עוף", "עוף והודו", _KG, r"^ ?(כרעיים|כרע)( עוף| טרי| שלמים|$| )", r"קפוא|מתובל|צלוי|הודו|אווז|ברווז", None),
    ("chicken-drumsticks", "שוקיים עוף", "עוף והודו", _KG, r"^ ?(שוקיים|שוקי|שוק) עוף", r"קפוא|מתובל|צלוי|הודו|אווז", None),
    ("chicken-wings", "כנפיים עוף", "עוף והודו", _KG, r"^ ?(כנפיים|כנף|כנפי) עוף", r"קפוא|מתובל|צלוי|בגריל|הודו|ברביקיו|מוכן", None),
    ("chicken-pargiot", "פרגיות עוף", "עוף והודו", _KG, r"^ ?(פרגיות|פרגית)( עוף| טרי| שלמות|$| )", r"קפוא|מתובל|צלוי|שיפוד|סטייק|פסטרמה|בגריל|נקניק|קבב|רבעי", None),
    ("chicken-liver", "כבד עוף", "עוף והודו", _KG, r"^ ?כבד (עוף|טרי)", r"קפוא|קצוץ|ממרח|פטה|מטוג|הודו|אווז|בקר", None),
    ("chicken-hearts", "לבבות עוף", "עוף והודו", _KG, r"^ ?(לבבות|לב) עוף", r"קפוא|מתובל", None),
    ("chicken-ground", "עוף טחון", "עוף והודו", _KG, r"^ ?(עוף טחון|בשר טחון עוף|חזה עוף טחון|טחון עוף)", r"הודו|בקר|קבב|מתובל", None),
    ("turkey-breast", "חזה הודו", "עוף והודו", _KG, r"^ ?חזה הודו", r"מעושן|פסטרמה|צלוי|פרוס|נקניק|שיפוד|מתובל|בגריל|מעודן|ברביקיו", None),
    ("turkey-shawarma", "שווארמה הודו", "עוף והודו", _KG, r"^ ?שווארמה (הודו|פרגית|עוף)|^ ?בשר שווארמה", r"מוכן|צלוי|בגריל|מטוג|צועני", None),

    # ---- בשר ----
    ("beef-ground", "בשר בקר טחון", "בשר", _KG, r"^ ?(בשר )?(בקר )?טחון|^ ?בשר טחון", r"עוף|הודו|צמחי|ביונד|טבעול|קבב|מוכן|כבש|טלה|תבלין|עגל", {"must": r"טחון"}),
    ("beef-shoulder", "צלי כתף", "בשר", _KG, r"^ ?(צלי )?כתף( בקר| טרי| מס| $|$| )|^ ?צלי כתף", r"כבש|טלה|עגל|קפוא|הודו|עוף|צלוי", None),
    ("beef-shank", "שריר בקר", "בשר", _KG, r"^ ?שריר (הזרוע|בקר|טרי|קדמי|אחורי)|^ ?שריר $", r"עגל|כבש|קפוא", None),
    ("beef-entrecote", "אנטריקוט", "בשר", _KG, r"^ ?(סטייק )?אנטריקוט", r"עגל|כבש|קפוא|אצבעות|פרוס|קבב|המבורגר|מתובל|מוקפץ", None),
    ("beef-sinta", "סינטה", "בשר", _KG, r"^ ?(סטייק )?סינטה", r"עגל|כבש|קפוא|פרוס", None),
    ("beef-brisket", "בריסקט / חזה בקר", "בשר", _KG, r"^ ?(בריסקט|חזה בקר)", r"מעושן|פסטרמה|קפוא|מבושל|צלוי", None),
    ("beef-asado", "אסאדו", "בשר", _KG, r"^ ?אסאדו", r"קפוא|מבושל|מעושן", None),
    ("beef-goulash", "בשר לגולאש / תבשיל", "בשר", _KG, r"^ ?(גולש|גולאש|בשר (לגולש|לגולאש|לתבשיל|בקר לתבשיל))", r"עגל|כבש|קפוא", None),
    ("beef-fillet", "פילה בקר", "בשר", _KG, r"^ ?פילה (בקר|בקר טרי)", r"מדומה|עגל|קפוא", None),
    ("beef-false-fillet", "פילה מדומה", "בשר", _KG, r"^ ?(פילה מדומה|צלי פילה מדומה)", r"קפוא|עגל", None),
    ("lamb-shoulder", "כתף כבש", "בשר", _KG, r"^ ?כתף (כבש|טלה)", r"קפוא|צלוי", None),

    # ---- דגים ----
    ("fish-salmon", "פילה סלמון", "דגים", _KG, r"^ ?(פילה )?סלמון", r"מעושן|קפוא|קוביות|נתחים|כבוש|בורגר|שיפוד|ממולא|פרוס|טרטר", {"must": r"פילה|טרי|סלמון נורבגי|סלמון $"}),
    ("fish-tilapia", "פילה אמנון טרי", "דגים", _KG, r"^ ?(פילה )?(אמנון|מושט|נסיכת הנילוס)", r"קפוא|מטוג|צלוי|מוכן|ממולא|שלם| \d{1,2} \d{1,2} |ואקו|וואקום| 80 | 90 |עם עור|יפני", {"must": r"^(?=.* פילה )(?=.* טרי )"}),
    ("fish-tilapia-vac", "פילה אמנון קפוא / בוואקום", "דגים", _KG, r"^ ?(פילה )?(אמנון|מושט|נסיכת הנילוס)", r"מטוג|צלוי|מוכן|ממולא|שלם|טרי", {"must": r"פילה"}),
    ("fish-tilapia-whole", "אמנון שלם", "דגים", _KG, r"^ ?(אמנון|מושט)( שלם| טרי| נקי|$| )", r"פילה|קפוא|מטוג|צלוי", None),
    ("fish-denis", "פילה דניס", "דגים", _KG, r"^ ?(פילה )?(דניס|צ.פורה)", r"קפוא|שלם|מטוג", {"must": r"פילה"}),
    ("fish-sea-bass", "פילה לברק טרי", "דגים", _KG, r"^ ?(פילה )?(לברק|לוקוס)", r"קפוא|שלם|מטוג| \d{1,2} \d{1,2} |ואקו|וואקום| 80 | 90 |עם עור|יפני", {"must": r"פילה"}),
    ("fish-sea-bass-vac", "פילה לברק קפוא / בוואקום", "דגים", _KG, r"^ ?(פילה )?(לברק|לוקוס)", r"שלם|מטוג|טרי", {"must": r"פילה"}),
    ("fish-hake", "פילה מרלוזה / הייק", "דגים", _KG, r"^ ?(פילה )?(מרלוזה|הייק|בקלה)", r"מטוג|מצופה|שניצל|צלוי|בורגר|קציצ", {"must": r"פילה"}),
    ("fish-tuna-steak", "סטייק טונה", "דגים", _KG, r"^ ?סטייק טונה|^ ?טונה (אדומה|אלבקור|טרייה)", r"שימורים|בשמן|במים|קופסא|מעושן|מעושנת", None),

    # ---- ירקות ----
    ("veg-tomato", "עגבנייה", "ירקות", _KG, r"^ ?(עגבניה|עגבנייה|עגבניות)( |$)", r"שרי|תמר|מגי|מיובש|רוטב|רסק|מרוסק|קצוץ|קלוף|אורגני|ענבים|צהוב|שחור|טבעית|בשרני", None),
    ("veg-tomato-cherry", "עגבניות שרי", "ירקות", _KG, r"^ ?(עגבניות|עגבניה|עגבנייה)? ?שרי( |$)", r"מיובש|רוטב|תמר|צהוב|מגי|שוקולד|ליקר|אדום|מנומר|אורגני", None),
    ("veg-cucumber", "מלפפון", "ירקות", _KG, r"^ ?(מלפפון|מלפפונים)( |$)", r"חמוץ|חריף|כבוש|בחומץ|מיני|בייבי|פרסי|אורגני|צנצנת|בשמיר", None),
    ("veg-pepper-red", "פלפל אדום", "ירקות", _KG, r"^ ?פלפל אדום", r"חריף|קלוי|מיובש|גריל|צנצנת|כבוש|טחון|גרוס|פפריקה|ממולא|אורגני|מיני|צ.ילי", None),
    ("veg-pepper-yellow", "פלפל צהוב", "ירקות", _KG, r"^ ?פלפל צהוב", r"חריף|קלוי|מיובש|מיני|אורגני", None),
    ("veg-pepper-orange", "פלפל כתום", "ירקות", _KG, r"^ ?פלפל כתום", r"חריף|קלוי|מיובש|מיני|אורגני", None),
    ("veg-pepper-green", "פלפל ירוק", "ירקות", _KG, r"^ ?פלפל ירוק", r"חריף|קלוי|כבוש|מיובש|צ.ילי|שושקה|אורגני", None),
    ("veg-pepper-hot", "פלפל חריף", "ירקות", _KG, r"^ ?פלפל חריף", r"כבוש|מיובש|טחון|גרוס|רוטב|צנצנת|ממרח|אורגני", None),
    ("veg-onion", "בצל יבש", "ירקות", _KG, r"^ ?בצל( יבש| לבן| צהוב|$| ארוז| בתפזורת| רשת)", r"ירוק|סגול|אדום|שאלוט|מטוג|טבעות|מיובש|אבקה|קצוץ|פנינה|אורגני|מתוק", None),
    ("veg-onion-red", "בצל סגול", "ירקות", _KG, r"^ ?בצל (אדום|סגול)", r"מטוג|מיובש|קצוץ|אורגני|כבוש", None),
    ("veg-potato", "תפוח אדמה", "ירקות", _KG, r"^ ?(תפוח אדמה|תפוחי אדמה|תפוא|תפו א)( |$)", r"בטטה|צ.יפס|פירה|אפוי|מטוג|קפוא|קלוף|אורגני|מיני|בייבי|אדום|לאפייה|דוד", None),
    ("veg-sweet-potato", "בטטה", "ירקות", _KG, r"^ ?בטטה", r"צ.יפס|קפוא|אפוי|מטוג|קלוף|פירה|אורגני|חתוכ", None),
    ("veg-carrot", "גזר", "ירקות", _KG, r"^ ?גזר( |$)", r"מגורד|מבושל|גמדי|בייבי|מיץ|קצוץ|אורגני|צבעוני|סלט|מקולף", None),
    ("veg-zucchini", "קישוא", "ירקות", _KG, r"^ ?(קישוא|קישואים)( |$)", r"ממולא|קפוא|אורגני|צהוב|בייבי|עגול|ספגטי", None),
    ("veg-eggplant", "חציל", "ירקות", _KG, r"^ ?(חציל|חצילים)( |$)", r"קלוי|מטוג|סלט|מעדן|בטחינה|במיונז|צנצנת|שרוף|ממולא|בייבי|לבן|אורגני", None),
    ("veg-cabbage-white", "כרוב לבן", "ירקות", _KG, r"^ ?כרוב( לבן|$| )", r"אדום|סגול|כבוש|חמוץ|במלח|סלט|ניצני|קצוץ|גמדי|פרוס|סיני|נאפה|טורקי|כרובית|תרד|אורגני", None),
    ("veg-cabbage-red", "כרוב אדום", "ירקות", _KG, r"^ ?כרוב (אדום|סגול)", r"כבוש|חמוץ|סלט|קצוץ|אורגני|פרוס", None),
    ("veg-cauliflower", "כרובית", "ירקות", _KG, r"^ ?כרובית( |$)", r"קפוא|אורגני|מוקפץ|פרחי|אורז|קצוץ|ברוקולי|מטוג", None),
    ("veg-broccoli", "ברוקולי", "ירקות", _KG, r"^ ?ברוקולי( |$)", r"קפוא|אורגני|פרחי|מוקפץ", None),
    ("veg-kohlrabi", "קולורבי", "ירקות", _KG, r"^ ?קולורבי", r"אורגני|סלט", None),
    ("veg-beet", "סלק אדום", "ירקות", _KG, r"^ ?סלק( אדום|$| )", r"מבושל|ארוז בוואקום|וואקום|סלט|חמוץ|כבוש|מיץ|עלי|אורגני|בייבי|מגורד", None),
    ("veg-pumpkin", "דלעת", "ירקות", _KG, r"^ ?דלעת( |$)", r"גרעין|מרק|קפוא|אורגני|ספגטי|ערמונים|יפנית|חמאה|קלויה|מחית", None),
    ("veg-butternut", "דלעת ערמונים", "ירקות", _KG, r"^ ?דלעת (ערמונים|חמאה|בטרנאט)", r"קפוא|אורגני|מרק", None),
    ("veg-fennel", "שומר", "ירקות", _KG, r"^ ?שומר( |$)", r"זרעי|טחון|תה|אורגני", None),
    ("veg-green-beans", "שעועית ירוקה", "ירקות", _KG, r"^ ?(שעועית ירוקה|לוביה)( |$)", r"קפוא|שימורים|צנצנת|אורגני|דקה", None),
    ("veg-corn", "תירס", "ירקות", _KG, r"^ ?תירס( טרי| ארוז| קלחים| קלח|$| )", r"שימורים|קפוא|גרעיני|קופסא|מתוק במים|פופקורן|קורנפלקס|קמח|שמן|מקלוני|מבושל|וואקום|שניצל|ביסלי|צ.יפס", None),
    ("veg-garlic", "שום", "ירקות", _KG, r"^ ?שום( |$)", r"כתוש|גבישי|מיובש|אבקה|גרוס|קלוף|מטוג|קפוא|שמיר|צנצנת|שחור|ממרח|במלח|גבינ|מקולף|אורגני", None),

    # ---- פירות ----
    ("fruit-banana", "בננה", "פירות", _KG, r"^ ?(בננה|בננות)( |$)", r"צ.יפס|מיובש|משקה|יוגורט|שוקו|אורגני|קפוא|מחית|טופי", None),
    ("fruit-apple", "תפוח עץ", "פירות", _KG, r"^ ?(תפוח|תפוחי|תפו) (עץ|ע )|^ ?תפוח (גאלה|גרני|פינק|חרמון|יונתן|סמית|סטארקינג|זהוב|אדום|ירוק|ענבר|פוג.י)|^ ?תפו ע( |$)", r"מיובש|משקה|מיץ|רסק|מחית|צ.יפס|אורגני|שוקו|טבעות|אפוי|קינמון|חמוץ", None),
    ("fruit-orange", "תפוז", "פירות", _KG, r"^ ?(תפוז|תפוזים)( |$)", r"מיץ|משקה|סחוט|מיובש|קליפות|דם|שוקו|טבעי|ליקר|תפוזינה|אורגני|ריבה", None),
    ("fruit-clementine", "קלמנטינה", "פירות", _KG, r"^ ?(קלמנטינה|קלמנטינות|מנדרינה|אור)( |$)", r"מיץ|משקה|שימורים|אורגני", None),
    ("fruit-lemon", "לימון", "פירות", _KG, r"^ ?(לימון|לימונים)( |$)", r"מיץ|משקה|לימונענע|לימונדה|כבוש|תה|גלידה|סבון|ניקוי|אורגני|קליפ|ליים|עוגת|וופל|מיובש|טעם", None),
    ("fruit-avocado", "אבוקדו", "פירות", _KG, r"^ ?אבוקדו( |$)", r"שמן|ממרח|גוואקמולי|אורגני|קפוא|מיני|בייבי|קרם|ממולא", None),
    ("fruit-mango", "מנגו", "פירות", _KG, r"^ ?מנגו( |$)", r"מיובש|משקה|קפוא|מחית|רוטב|אורגני|נקטר|ליקר|מיץ|סירופ|צ.אטני|גלידה", None),
    ("fruit-peach", "אפרסק", "פירות", _KG, r"^ ?(אפרסק|אפרסקים)( |$)", r"שימורים|מיובש|משקה|נקטר|מחית|אורגני|בסירופ|טעם", None),
    ("fruit-nectarine", "נקטרינה", "פירות", _KG, r"^ ?(נקטרינה|נקטרינות)( |$)", r"מיובש|אורגני", None),
    ("fruit-plum", "שזיף", "פירות", _KG, r"^ ?(שזיף|שזיפים)( |$)", r"מיובש|מגולען|ריבה|אורגני|מחית", None),
    ("fruit-pear", "אגס", "פירות", _KG, r"^ ?(אגס|אגסים)( |$)", r"מיובש|שימורים|משקה|מחית|אורגני|נקטר|בסירופ", None),
    ("fruit-grapes", "ענבים", "פירות", _KG, r"^ ?(ענבים|ענב)( |$)", r"מיץ|צימוק|יין|מיובש|עלי|אורגני|שימורים", None),
    ("fruit-melon", "מלון", "פירות", _KG, r"^ ?מלון( |$)", r"מיובש|אורגני|גלידה|חתוך|קוביות", None),
    ("fruit-watermelon", "אבטיח", "פירות", _KG, r"^ ?(אבטיח|אבטיחים)( |$)", r"גרעין|גרעיני|מיץ|משקה|חתוך|קוביות|אורגני|חצי|רבע", None),
    ("fruit-pomegranate", "רימון", "פירות", _KG, r"^ ?(רימון|רימונים)( |$)", r"מיץ|גרעיני|משקה|רכז|סירופ|אורגני|מולסה", None),
    ("fruit-kiwi", "קיווי", "פירות", _KG, r"^ ?קיווי( |$)", r"מיובש|אורגני|משקה|גולד|ארוז", None),
    ("fruit-grapefruit", "אשכולית", "פירות", _KG, r"^ ?(אשכולית|אשכוליות)( |$)", r"מיץ|משקה|אורגני|סחוט", None),
    ("fruit-persimmon", "אפרסמון", "פירות", _KG, r"^ ?(אפרסמון|אפרסמונים)( |$)", r"מיובש|אורגני", None),
    ("fruit-pomelit", "פומלית", "פירות", _KG, r"^ ?(פומלית|פומלה)( |$)", r"מיץ|אורגני|משקה", None),

    # ---- ביצים וירוקים (ליחידה) ----
    ("eggs-l-12", "ביצים L (12)", "ביצים", _UNIT, r"(^| |\d)(ביצים|ביצי)( |$)", r"אומגה|חופש|אורגני|XL|ענק|אטריות|איטריות|נודלס|פסטה|פפרדלה|פטוצ|לזניה|ספגטי|מסטיק|שוקולד|הפתעה|קינדר|חביתה|שקשוקה|מקושקש|קשות|מבושל|אבקת|חלבון|סלט|כבוש|שליו|ברווז|דג|פורס|עוגיות|בישקוטי|מארז|חטיף|לחם|חלה|עוגת", {"size": r"(^|[^A-Za-z])L([^A-Za-z]|$)|גדול", "qty": 12}),
    ("eggs-m-12", "ביצים M (12)", "ביצים", _UNIT, r"(^| |\d)(ביצים|ביצי)( |$)", r"אומגה|חופש|אורגני|XL|ענק|אטריות|איטריות|נודלס|פסטה|פפרדלה|פטוצ|לזניה|ספגטי|מסטיק|שוקולד|הפתעה|קינדר|חביתה|שקשוקה|מקושקש|קשות|מבושל|אבקת|חלבון|סלט|כבוש|שליו|ברווז|דג|פורס|עוגיות|בישקוטי|מארז|חטיף|לחם|חלה|עוגת", {"size": r"(^|[^A-Za-z])M([^A-Za-z]|$)|בינוני|בנוני", "qty": 12}),
    ("eggs-l-18", "ביצים L (18)", "ביצים", _UNIT, r"(^| |\d)(ביצים|ביצי)( |$)", r"אומגה|חופש|אורגני|XL|ענק|אטריות|איטריות|נודלס|פסטה|פפרדלה|פטוצ|לזניה|ספגטי|מסטיק|שוקולד|הפתעה|קינדר|חביתה|שקשוקה|מקושקש|קשות|מבושל|אבקת|חלבון|סלט|כבוש|שליו|ברווז|דג|פורס|עוגיות|בישקוטי|מארז|חטיף|לחם|חלה|עוגת", {"size": r"(^|[^A-Za-z])L([^A-Za-z]|$)|גדול", "qty": 18}),
    ("eggs-l-30", "ביצים L (30)", "ביצים", _UNIT, r"(^| |\d)(ביצים|ביצי)( |$)", r"אומגה|חופש|אורגני|XL|ענק|אטריות|איטריות|נודלס|פסטה|פפרדלה|פטוצ|לזניה|ספגטי|מסטיק|שוקולד|הפתעה|קינדר|חביתה|שקשוקה|מקושקש|קשות|מבושל|אבקת|חלבון|סלט|כבוש|שליו|ברווז|דג|פורס|עוגיות|בישקוטי|מארז|חטיף|לחם|חלה|עוגת", {"size": r"(^|[^A-Za-z])L([^A-Za-z]|$)|גדול", "qty": 30}),
    ("herb-parsley", "פטרוזיליה (צרור)", "ירוקים", _UNIT, r"^ ?פטרוזיליה( |$)", r"יבשה|מיובש|קפוא|קצוצה|מימון|שקית|במיכל|צנצנת|קוביות|אורגני|שורש", {"bunch": True}),
    ("herb-coriander", "כוסברה (צרור)", "ירוקים", _UNIT, r"^ ?כוסברה( |$)", r"יבשה|מיובש|קפוא|קצוצה|מימון|שקית|במיכל|צנצנת|קוביות|טחונה|זרעי|אורגני", {"bunch": True}),
    ("herb-dill", "שמיר (צרור)", "ירוקים", _UNIT, r"^ ?שמיר( |$)", r"יבש|מיובש|קפוא|קצוץ|מימון|שקית|במיכל|צנצנת|קוביות|אורגני", {"bunch": True}),
    ("veg-lettuce", "חסה (ראש)", "ירוקים", _UNIT, r"^ ?חסה( |$)", r"קצוצה|שטופה|ארוזה|לליק|מיקס|עלי בייבי|בייבי|סלט|אורגני|אייסברג קצוצ|גרם|מגש", {"bunch": True}),
]

# Icon per generic product (key or key prefix); the page shows it in place of a photo.
ICONS = {
    "chicken": "🍗", "turkey": "🍗", "beef": "🥩", "lamb": "🥩", "fish": "🐟",
    "veg-tomato": "🍅", "veg-cucumber": "🥒", "veg-pepper-hot": "🌶️", "veg-pepper": "🫑", "veg-onion": "🧅",
    "veg-potato": "🥔", "veg-sweet-potato": "🍠", "veg-carrot": "🥕", "veg-zucchini": "🥒", "veg-eggplant": "🍆",
    "veg-cabbage": "🥬", "veg-cauliflower": "🥦", "veg-broccoli": "🥦", "veg-kohlrabi": "🥬", "veg-beet": "🍠",
    "veg-pumpkin": "🎃", "veg-butternut": "🎃", "veg-fennel": "🌿", "veg-green-beans": "🌱", "veg-corn": "🌽",
    "veg-garlic": "🧄", "veg-lettuce": "🥬",
    "fruit-banana": "🍌", "fruit-apple": "🍎", "fruit-orange": "🍊", "fruit-clementine": "🍊", "fruit-lemon": "🍋",
    "fruit-avocado": "🥑", "fruit-mango": "🥭", "fruit-peach": "🍑", "fruit-nectarine": "🍑", "fruit-plum": "🍑",
    "fruit-pear": "🍐", "fruit-grapes": "🍇", "fruit-melon": "🍈", "fruit-watermelon": "🍉", "fruit-pomegranate": "🍎",
    "fruit-kiwi": "🥝", "fruit-grapefruit": "🍊", "fruit-persimmon": "🍅", "fruit-pomelit": "🍈",
    "eggs": "🥚", "herb": "🌿",
}


def icon(key):
    """Longest matching key prefix wins ("veg-pepper-hot" before "veg-pepper")."""
    best = max((k for k in ICONS if key == k or key.startswith(k + "-") or key.startswith(k)), key=len, default=None)
    return ICONS[best] if best else "🛒"


# Words that never belong to a generic fresh product.
_GLOBAL_EXCLUDE = r"קולינרי|מזון לחתול|מזון לכלב|לחתולים|לכלבים|שקית|מגש חד|קיסמים"


def _norm(name: str) -> str:
    name = re.sub(r"[^A-Za-zא-ת0-9 ]", " ", name or "")
    return " " + " ".join(name.split()) + " "


def _compile(pattern, exclude=False):
    if not pattern:
        return None
    if exclude and "קפוא" in pattern:
        # A name cut short often ends in "קפ" / "קפו" for קפוא (frozen).
        pattern += r"| קפ $| קפו $"
    return re.compile(pattern.replace("^ ?", "^ "))


_RULES = []
for key, name, cat, unit, match, exclude, extra in CATALOG:
    extra = extra or {}
    _RULES.append({
        "key": key, "name": name, "category": cat, "unit": unit,
        "match": _compile(match), "exclude": _compile(exclude, exclude=True),
        "must": _compile(extra.get("must")), "size": _compile(extra.get("size")),
        "qty": extra.get("qty"), "bunch": extra.get("bunch", False),
    })
_GLOBAL = re.compile(_GLOBAL_EXCLUDE)

_KG_UNITS = re.compile(r"קילו|ק\"ג|קג|kg", re.I)


def _per_kg(item):
    """The item's price per kg, or None when it isn't sold by weight."""
    if item["weighted"]:
        return item["price"]
    # A 1 kg pack of a fresh product ("בשר טחון עוף 1 קג") is priced per kg too.
    if item["quantity"] == 1 and _KG_UNITS.search(item["unit"] or ""):
        return item["price"]
    return None


def _candidates(rule, item, norm):
    """Return the comparable price for `item` under `rule`, or None."""
    if not rule["match"].search(norm) or _GLOBAL.search(norm):
        return None
    if rule["exclude"] and rule["exclude"].search(norm):
        return None
    if rule["must"] and not rule["must"].search(norm):
        return None
    if rule["unit"] == _KG:
        return _per_kg(item)
    if item["weighted"]:
        return None
    if rule["size"] and not rule["size"].search(item["name"] or ""):
        return None
    if rule["qty"]:
        q = item["quantity"] or 0
        in_name = re.search(rf"(^|\D){rule['qty']}(\D|$)", item["name"] or "")
        is_units = "יח" in (item["unit"] or "")
        if not ((is_units and q == rule["qty"]) or (in_name and (is_units or q in (0, 1)))):
            return None
    if rule["bunch"]:
        # A bunch is sold per unit; packaged/chopped herbs are priced per gram.
        if (item["quantity"] or 0) > 1 or re.search(r"גר", item["unit"] or ""):
            return None
    return item["price"]


def match_store(items):
    """{rule key: [(price, item name), ...]} for one store's items."""
    out = {}
    for item in items:
        norm = _norm(item["name"])
        for rule in _RULES:
            price = _candidates(rule, item, norm)
            if price:
                out.setdefault(rule["key"], []).append((price, item["name"]))
    return out


def pick_prices(per_store):
    """Choose one price per store and generic product.

    per_store: [{rule key: [(price, name)]}] aligned with stores.
    Returns [{rule key: (price, name)}]. A store's cheapest match wins, except
    prices below 45% of the product's typical price, which are almost always a
    mis-coded or partial item (e.g. a 100 g pack flagged as weighted).
    """
    typical = {}
    for rule in _RULES:
        prices = [p for store in per_store for p, _ in store.get(rule["key"], [])]
        if prices:
            typical[rule["key"]] = statistics.median(prices)
    out = []
    for store in per_store:
        chosen = {}
        for key, cands in store.items():
            floor = typical[key] * 0.45
            ok = sorted(c for c in cands if c[0] >= floor)
            if ok:
                chosen[key] = ok[0]
        out.append(chosen)
    return out


def catalog():
    return [(r["key"], r["name"], r["category"], r["unit"], icon(r["key"])) for r in _RULES]
