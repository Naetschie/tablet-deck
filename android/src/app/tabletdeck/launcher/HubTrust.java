package app.tabletdeck.launcher;

import android.content.Context;
import android.net.http.SslCertificate;
import android.util.Base64;
import android.util.Log;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;

/**
 * Vertrauen in den WLAN-Zugang des Hubs, ohne die CA in die APK einzubauen (Weitergabe: eine APK für alle PCs).
 *
 * Der Hub schickt beim Anstecken per ADB seine CA (Wurzel + Zwischen-CA, nur öffentliche Zertifikate) an den
 * PairingReceiver - nur die ADB-Shell darf ihn aufrufen. Geprüft wird ausschließlich für die Hub-Adressen
 * (HubLink.isHubUrl): Kette Server -> Zwischen-CA -> gespeicherte Wurzel per PKIX (setzt die NameConstraints
 * der Zwischen-CA durch: nur private IPv4) und die IP-Adresse im Server-Zertifikat. Die Web-Kachel und alle
 * anderen Verbindungen vertrauen weiter nur den System-CAs - anders als früher, als die eingebettete Wurzel
 * app-weit galt.
 */
final class HubTrust {
    private static final String FILE = "hub_ca.pem";
    private static final int MAX_PEM = 16 * 1024;
    private static final Object LOCK = new Object();
    private static long loadedStamp = -1;
    private static X509TrustManager trust;
    private static X509Certificate inter;
    private static SSLSocketFactory sockets;

    private HubTrust() {
    }

    /**
     * Vom PairingReceiver: Base64 eines PEM-Bündels mit genau zwei Zertifikaten (Wurzel, Zwischen-CA). Wird nur
     * gespeichert, wenn die Wurzel selbstsigniert ist und die Zwischen-CA von ihr stammt. true bei Erfolg.
     */
    static boolean store(Context ctx, String b64) {
        try {
            byte[] pem = Base64.decode(b64, Base64.DEFAULT);
            if (pem.length == 0 || pem.length > MAX_PEM) return false;
            X509Certificate[] rc = parse(pem);
            if (rc == null) return false;
            File dir = ctx.getFilesDir();
            File tmp = new File(dir, FILE + ".tmp");
            try (FileOutputStream f = new FileOutputStream(tmp)) {
                f.write(pem);
                f.getFD().sync();
            }
            if (!tmp.renameTo(new File(dir, FILE))) {
                tmp.delete();
                return false;
            }
            synchronized (LOCK) {
                loadedStamp = -1;   // beim nächsten Zugriff neu laden
            }
            return true;
        } catch (Exception e) {
            Log.w(HomeActivity.TAG, "Hub-CA ungültig: " + e);
            return false;
        }
    }

    /** {Wurzel, Zwischen-CA} oder null, wenn das Bündel nicht genau so aufgebaut ist. */
    private static X509Certificate[] parse(byte[] pem) throws Exception {
        CertificateFactory cf = CertificateFactory.getInstance("X.509");
        Collection<? extends java.security.cert.Certificate> all = cf.generateCertificates(new ByteArrayInputStream(pem));
        List<X509Certificate> certs = new ArrayList<>();
        for (java.security.cert.Certificate c : all) certs.add((X509Certificate) c);
        if (certs.size() != 2) return null;
        X509Certificate root = certs.get(0), mid = certs.get(1);
        if (root.getBasicConstraints() < 0 || mid.getBasicConstraints() < 0) return null;   // beide CAs
        if (!root.getSubjectX500Principal().equals(root.getIssuerX500Principal())) return null;
        root.verify(root.getPublicKey());     // selbstsigniert
        mid.verify(root.getPublicKey());      // Zwischen-CA von dieser Wurzel
        return new X509Certificate[]{root, mid};
    }

    /** Lädt das gespeicherte Bündel (nach Änderung neu). false, wenn keins da ist. */
    private static boolean load(Context ctx) {
        File f = new File(ctx.getFilesDir(), FILE);
        synchronized (LOCK) {
            long stamp = f.exists() ? f.lastModified() ^ f.length() : 0;
            if (stamp == loadedStamp) return trust != null;
            loadedStamp = stamp;
            trust = null;
            inter = null;
            sockets = null;
            if (stamp == 0) return false;
            try {
                byte[] pem = java.nio.file.Files.readAllBytes(f.toPath());
                X509Certificate[] rc = parse(pem);
                if (rc == null) return false;
                KeyStore ks = KeyStore.getInstance(KeyStore.getDefaultType());
                ks.load(null, null);
                ks.setCertificateEntry("hub-root", rc[0]);   // nur die Wurzel ist Vertrauensanker
                TrustManagerFactory tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
                tmf.init(ks);
                for (TrustManager tm : tmf.getTrustManagers()) {
                    if (tm instanceof X509TrustManager) trust = (X509TrustManager) tm;
                }
                inter = rc[1];
                SSLContext sc = SSLContext.getInstance("TLS");
                sc.init(null, new TrustManager[]{trust}, null);
                sockets = sc.getSocketFactory();
                return trust != null;
            } catch (Exception e) {
                Log.w(HomeActivity.TAG, "Hub-CA nicht ladbar: " + e);
                trust = null;
                return false;
            }
        }
    }

    /** TLS für HubLink.probe (HttpsURLConnection): nur die Hub-CA, Hostname prüft die Verbindung selbst. */
    static SSLSocketFactory socketFactory(Context ctx) {
        synchronized (LOCK) {
            return load(ctx) ? sockets : null;
        }
    }

    /**
     * WebView meldet für eine Hub-Adresse einen Zertifikatsfehler (die APK kennt die CA nicht): Server-Zertifikat
     * selbst prüfen. host = IP-Adresse aus der URL.
     */
    static boolean verify(Context ctx, SslCertificate sc, String host) {
        X509TrustManager tm;
        X509Certificate mid;
        synchronized (LOCK) {
            if (!load(ctx)) return false;
            tm = trust;
            mid = inter;
        }
        try {
            X509Certificate leaf = sc == null ? null : sc.getX509Certificate();
            if (leaf == null || host == null) return false;
            tm.checkServerTrusted(new X509Certificate[]{leaf, mid}, "ECDHE_ECDSA");   // PKIX inkl. NameConstraints
            return hasIp(leaf, host);
        } catch (Exception e) {
            Log.w(HomeActivity.TAG, "Hub-Zertifikat abgelehnt: " + e);
            return false;
        }
    }

    /** Steht host als IP-Adresse (SAN-Typ 7) im Zertifikat? */
    static boolean hasIp(X509Certificate cert, String host) throws Exception {
        Collection<List<?>> sans = cert.getSubjectAlternativeNames();
        if (sans == null) return false;
        for (List<?> san : sans) {
            if (san.size() >= 2 && Integer.valueOf(7).equals(san.get(0)) && host.equals(san.get(1))) return true;
        }
        return false;
    }

    /** Für Tests/Diagnose: ist eine CA gespeichert? */
    static boolean present(Context ctx) {
        synchronized (LOCK) {
            return load(ctx);
        }
    }
}
