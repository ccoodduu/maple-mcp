// Standalone launcher that renders a Maple .mw document to PDF using Maple's
// own GUI export pipeline (the same path as File > Export As > PDF).
//
// It parses the .mw from disk into a fresh in-memory model, so it does NOT
// touch (or require) the user's open Maple window — it works even if Maple is
// closed. Run inside Maple's bundled JVM with the full java/ classpath:
//
//   java -Djava.library.path=<MAPLE>/bin.X86_64_WINDOWS \
//        -cp "<MAPLE>/java/*;maple-export.jar" MapleExport <in.mw> <out.pdf>
//
// Must run NON-headless: the PDF formatter constructs (invisible) Swing owner
// frames internally and throws HeadlessException under -Djava.awt.headless=true.
//
// Maple's export API is resolved REFLECTIVELY, exactly like ReloadAgent does.
// That keeps this jar free of any compile-time link against a specific Maple's
// worksheet.jar, so ONE jar serves every Maple version and the build needs no
// -cp. When a future Maple moves or renames the API, the failure is a readable
// message naming the missing class/method instead of a NoClassDefFoundError.
//
//   javac -d _b java/MapleExport.java        # no Maple classpath required
//   jar cfe maple-export.jar MapleExport -C _b MapleExport.class
//
// Probe mode reports whether the API resolves on a given Maple install without
// exporting anything — and without needing a Maple licence, since resolution is
// pure classloading. Use it as the first check when porting to a new Maple:
//
//   java -cp "<MAPLE>/java/*;maple-export.jar" MapleExport --probe

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

public class MapleExport {
    private static final String EXPORT_CLASS =
            "com.maplesoft.worksheet.util.WmiWorksheetExportUtils";
    private static final String EXPORT_METHOD = "exportPDF";

    public static void main(String[] args) {
        if (args.length == 1 && args[0].equals("--probe")) {
            System.exit(probe());
        }
        if (args.length < 2) {
            System.err.println("usage: MapleExport <in.mw> <out.pdf>");
            System.err.println("       MapleExport --probe");
            System.exit(2);
        }
        try {
            resolveExport().invoke(null, args[0], args[1]);
            System.out.println("OK");
            System.exit(0);
        } catch (InvocationTargetException ite) {
            // Unwrap: maple_render.py surfaces the FIRST Exception/Error line as the
            // cause, and it sniffs that text for HeadlessException / "no screen
            // device". A bare InvocationTargetException would mask both.
            Throwable cause = ite.getCause() != null ? ite.getCause() : ite;
            cause.printStackTrace();
            System.exit(1);
        } catch (Throwable t) {
            t.printStackTrace();
            System.exit(1);
        }
    }

    private static Method resolveExport() throws Exception {
        Class<?> util;
        try {
            util = Class.forName(EXPORT_CLASS);
        } catch (ClassNotFoundException e) {
            throw new IllegalStateException(
                    "Maple export API Error: class " + EXPORT_CLASS + " is not on the "
                    + "classpath. Either -cp is missing <MAPLE>/java/*, or this Maple "
                    + "version moved/renamed the export API.");
        }
        try {
            return util.getMethod(EXPORT_METHOD, String.class, String.class);
        } catch (NoSuchMethodException e) {
            throw new IllegalStateException(
                    "Maple export API Error: " + EXPORT_CLASS + "." + EXPORT_METHOD
                    + "(String, String) not found — the signature changed in this Maple "
                    + "version. Candidates present: " + candidates(util));
        }
    }

    private static String candidates(Class<?> util) {
        List<String> found = new ArrayList<>();
        for (Method m : util.getMethods()) {
            if (!m.getName().toLowerCase().contains("export")) {
                continue;
            }
            StringBuilder sb = new StringBuilder(m.getName()).append('(');
            Class<?>[] ps = m.getParameterTypes();
            for (int i = 0; i < ps.length; i++) {
                if (i > 0) {
                    sb.append(", ");
                }
                sb.append(ps[i].getSimpleName());
            }
            found.add(sb.append(')').toString());
        }
        return found.isEmpty() ? "(none)" : String.join(", ", found);
    }

    // Resolution only — never invokes the export, so it needs no licence and no
    // desktop session. Exit 0 = this Maple is compatible.
    private static int probe() {
        System.out.println("java.version=" + System.getProperty("java.version"));
        try {
            Method m = resolveExport();
            System.out.println("class=" + EXPORT_CLASS + " OK");
            System.out.println("method=" + m.getName() + "(String, String) OK");
            System.out.println("PROBE OK");
            return 0;
        } catch (Throwable t) {
            System.out.println("PROBE FAILED");
            System.err.println(t.getMessage() != null ? t.getMessage() : t.toString());
            return 1;
        }
    }
}
