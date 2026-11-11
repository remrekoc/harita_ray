# Harita Ray

**Türkiye Raylı Sistemler:** Türkiye'de yolcu taşıyan tüm demiryolu ve raylı sistem hatları tek haritada: yüksek hızlı tren (YHT), ana hat ve bölgesel trenler, banliyö (Marmaray, İZBAN, Başkentray, Gaziray, Adaray), metro, tramvay, füniküler ve teleferik.

Site: https://haritaray.pages.dev/

Üstteki düğmelerden bir şehir seçin: harita o şehre gider, o şehrin hatlarıyla oraya uğrayan şehirlerarası trenler öne çıkar, panel şehrin sayfasına geçer. Türler süzgeçle seçilir: bir türe (ya da **Şehirlerarası**, **Şehir içi** grubuna) tıklayınca haritada yalnız o kalır, tıklanan her tür eklenir, yeniden tıklanan çıkar; **Sıfırla** hepsini geri getirir. Hat ve istasyon sayfalarının üstündeki düğme tek tıkla listeye döner. Bir hatta tıklayın: uzunluğu, istasyonları, aktarmaları ve kaynağıyla birlikte yıllık ve ortalama günlük yolcu sayısı açılır. Sağ üstteki **Çizgi kalınlığı: günlük yolcu** anahtarı hatları yolcu sayısına göre kalınlaştırır (kalınlık yolcu sayısının kareköküyle büyür, alan doğru okunur).

Masaüstünde sol paneli kenarındaki okla gizleyip haritayı tam genişlikte kullanabilirsiniz; harita Türkiye'nin dışına kaydırılamaz.

Bağlantılar: `#izmir` bir şehri, `#istanbul-m2` ya da `#yht-ankara-istanbul` bir hattı, `#istasyon/<ad>` bir istasyonu, `#ozet` özet sekmesini açar.

## Dosyalar

| Dosya | İçerik |
|---|---|
| `index.html` | Sayfa iskeleti ve sayfa bilgileri (başlık, açıklama, paylaşım önizlemesi) |
| `style.css` | Görünüm |
| `app.js` | Harita, panel, şehir düğmeleri ve etkileşimler |
| `data/lines.json` | Şehirler, her hat ya da sefer için bir kayıt (yolcu sayısı ve kaynağıyla), TCDD toplamları |
| `data/network.geojson` | Her hattın güzergâhı ve sırasıyla istasyonları |
| `data/base.geojson` | Demiryolu ağının geri kalanı: yolcu treni çalışmayan hatlar ve yapımdaki hatlar (soluk) |
| `assets/` | Logo (`favicon.svg`), simgeler ve paylaşım görseli (`og-image.png`) |
| `site.webmanifest` | Ana ekrana eklenince kullanılan ad ve simgeler |
| `build/` | Veriyi yeniden üreten betikler ve kaynaklı yolcu verisi (ham OSM önbelleği `build/cache/` depoya girmez, `fetch.py` yeniden indirir) |

Derleme adımı yoktur. Harita [MapLibre GL](https://maplibre.org) ile çizilir; altlıklar [OpenFreeMap](https://openfreemap.org) (OpenStreetMap verisi) ve Esri uydu görüntüsüdür.

## Veri kaynakları ve lisanslar

- **Güzergâhlar ve istasyonlar:** © [OpenStreetMap katkıcıları](https://www.openstreetmap.org/copyright), [ODbL](https://opendatacommons.org/licenses/odbl/) lisansıyla. Overpass API ile alınır (`route=train|subway|light_rail|tram|monorail|funicular` ilişkileri, `railway=rail` yolları, istasyonlar). Haritadaki atıf bu lisansın gereğidir; veriyi yeniden kullanan da OSM'ye atıf vermeli ve türetilmiş veriyi aynı lisansla paylaşmalıdır.
- **İstanbul:** hat kayıtları, inşaat ilerlemesi ve planlanan hatlar `build/istanbul/lines.json` dosyasındadır; her hat bilgisinin kaynağı kaydın `sources` alanındadır. Güzergâh ve istasyonlar (`build/istanbul/network.geojson`) `build/istanbul_osm.py` ile OpenStreetMap'ten üretilir; hangi hattın hangi OSM ilişkisinden çizildiği betiğin başındaki `LINES` tablosundadır.
- **Şehirlerarası seferler:** hangi hat kesimlerinde tren çalıştığı, 18.09.2026 tarihli Resmî Gazete'deki 11800 sayılı Cumhurbaşkanı Kararı'ndaki kamu hizmeti yükümlülüğü listesinden (13 ana hat, 34 bölgesel kesim) ve Bakanlığın 2026'da açıkladığı dokuz YHT bağlantısından gelir. Güzergâh, varsa OSM'deki sefer ilişkisini izleyerek ray ağı üzerinde çizilir.
- **Yolcu sayıları:** her rakam yılı ve kaynak bağlantısıyla birlikte `build/ridership/*.json` dosyalarındadır: Metro İstanbul 2024 Faaliyet Raporu, İBB açık veri, EGO 2025 yolcu tablosu, İzmir Büyükşehir açık veri portalı, Bursa, Konya, Kayseri, Gaziantep, Samsun, Kocaeli ve Adana büyükşehir belediyelerinin 2025 faaliyet raporları, Sayıştay ESTRAM raporu, Ulaştırma ve Altyapı Bakanlığı açıklamaları (TRT Haber, DHA). Rakam tahmin edilmez: hat için ayrı rakam yoksa sayfada "Veri yok" yazar, varsa ağ ya da koridor toplamı "Grup verisi" olarak ayrıca gösterilir. Günlük değer kaynakta yoksa yıllık toplamın gün sayısına bölünmesiyle bulunur ve "ortalama günlük" diye yazılır. Yuvarlak rakamlar "≈" ile işaretlidir.

## Veriyi yeniden üretmek

Python 3 yeterlidir (ek paket gerekmez; indirmeler `curl` ile yapılır).

```
python3 build/fetch.py     # OSM verisini Overpass'tan indirir, build/cache/ altında saklar (var olanı yeniden indirmez)
python3 build/build.py     # data/ altındaki üç dosyayı üretir
```

İstanbul hatlarının güzergâhı OpenStreetMap'te düzeltildiyse önce `python3 build/istanbul_osm.py`, sonra `build.py` çalıştırılır.

`build/fetch.py --force` her şeyi yeniden indirir; tek bir sorgu için adını verin (ör. `python3 build/fetch.py stations`). Şehirlerarası seferlerin tanımı (uçlar, ara istasyonlar, OSM ilişkisi) `build/build.py` içindeki `INTERCITY` listesindedir; şehir içi hatların birleştirme ve ad düzeltmeleri `MERGE` ve `OVERRIDE` sözlüklerindedir. Yolcu rakamlarını eşleyen kurallar `build/ridership.py` içindedir. Yeni bir rakam eklemek için ilgili `build/ridership/*.json` dosyasına kaydı (yıl ve kaynakla) ekleyip `build.py`'yi yeniden çalıştırın.

`build/drive.mjs`, sayfayı başsız Chrome'da açıp ekran görüntüsü almak için kullanılan küçük bir yardımcıdır.

## Yerelde çalıştırmak

```
python3 -m http.server 8767
```

Sonra http://localhost:8767 adresini açın. `index.html` dosyayı doğrudan açarak çalışmaz, çünkü veri dosyaları sunucu üzerinden yüklenir.

## Lisans

- **Kod ve görseller** (`index.html`, `style.css`, `app.js`, `site.webmanifest`, `build/` altındaki betikler, `assets/` altındaki logo ve simgeler): [GNU GPL v3](LICENSE) ya da sonraki bir sürümü. © 2026 remrekoc. Paylaşım görseli `assets/og-image.png` OpenStreetMap verisinden çizildiği için OSM atfını taşır.
- **Veri** (`data/` ve `build/` altındaki JSON ve GeoJSON dosyaları): [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Güzergâh ve istasyonlar © [OpenStreetMap katkıcıları](https://www.openstreetmap.org/copyright); her rakamın ve hat bilgisinin kaynağı kendi kaydındadır.
- **Dışarıdan yüklenenler** depoda yer almaz ve kendi lisanslarıyla kullanılır: [MapLibre GL](https://github.com/maplibre/maplibre-gl-js) (BSD-3-Clause), Open Sans yazı tipi (SIL Open Font License), [OpenFreeMap](https://openfreemap.org) altlıkları (© OpenMapTiles, © OpenStreetMap katkıcıları) ve Esri uydu görüntüsü (Esri kullanım koşulları). Atıfları haritanın köşesinde görünür.

İstanbul bölümü [metroistiyorum.github.io](https://metroistiyorum.github.io)'dan esinlenmiştir; bu depo onun kodunu, metnini ya da verisini içermez.
