#include "mainwindow.h"

#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTemporaryDir>
#include <QThread>
#include <QToolButton>

#include <cstdio>
#include <functional>

static int failures = 0;
static void check(const char* name, bool ok) {
    std::printf("  %-64s %s\n", name, ok ? "ok" : "FAILED");
    if (!ok) ++failures;
}

static bool waitFor(const std::function<bool()>& condition, int timeout = 6000) {
    QElapsedTimer elapsed;
    elapsed.start();
    while (!condition() && elapsed.elapsed() < timeout) {
        QApplication::processEvents();
        QThread::msleep(10);
    }
    return condition();
}

static void pump(int milliseconds) {
    QElapsedTimer elapsed;
    elapsed.start();
    waitFor([&] { return elapsed.elapsed() >= milliseconds; }, milliseconds + 500);
}

static bool writeFile(const QString& path, const QByteArray& data, bool executable = false) {
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) return false;
    if (file.write(data) != data.size()) return false;
    file.close();
    return !executable || file.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner |
                                             QFileDevice::ExeOwner);
}

static QByteArray readFile(const QString& path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) return {};
    return file.readAll();
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    app.setQuitOnLastWindowClosed(false);
    QTemporaryDir fixture;
    if (!fixture.isValid()) return 1;
    const QString base = fixture.path();
    const QString config = base + "/config/dlssnr/config.ini";
    const QString calls = base + "/calls";
    const QString cli = base + "/mock-helper";
    const QString bundledWine = base + "/bundled-wine";
    qputenv("HOME", base.toUtf8());
    qputenv("XDG_CONFIG_HOME", (base + "/config").toUtf8());
    qputenv("XDG_DATA_HOME", (base + "/data").toUtf8());
    qputenv("XDG_STATE_HOME", (base + "/state").toUtf8());
    qputenv("DLSSNR_SHM", (base + "/runtime/shm.bin").toUtf8());
    qputenv("DLSSNR_INSTALL_DIR", (base + "/install").toUtf8());
    qputenv("DLSSNR_BUNDLED_RUNNER", bundledWine.toUtf8());
    qputenv("DLSSNR_TEST_CALLS", calls.toUtf8());
    qputenv("DLSSNR_HELPER_CLI", cli.toUtf8());
    check("create fixture model", writeFile(base + "/install/helper/binaries/nvngx_dlssnr.dll", "mock"));
    check("create fixture runner", writeFile(bundledWine, "#!/bin/sh\nexit 0\n", true));
    check("create fixture CLI", writeFile(cli,
        "#!/bin/sh\n"
        "printf '%s\\n' \"$1\" >> \"$DLSSNR_TEST_CALLS\"\n"
        "case \"$1\" in\n"
        "  doctor) echo 'checking runtime'; echo 'model fixture diagnostic' >&2; sleep 0.15; exit 2;;\n"
        "  start) echo 'preparing runtime'; sleep 1.4; if [ -f \"$DLSSNR_TEST_CALLS.retry\" ]; then exit 0; fi; echo 'download failed; try again' >&2; exit 17;;\n"
        "  stop) echo 'helper stopped'; exit 0;;\n"
        "esac\n", true));
    check("create stale config", writeFile(config, "runner_type=proton\nrunner_path=/missing/proton\nbinaries=/missing/models\n"));

    {
        MainWindow window;
        auto* start = window.findChild<QPushButton*>("startHelper");
        auto* stop = window.findChild<QPushButton*>("stopHelper");
        auto* doctor = window.findChild<QPushButton*>("checkSetup");
        auto* runner = window.findChild<QLineEdit*>("runnerPath");
        auto* status = window.findChild<QLabel*>("commandStatus");
        auto* details = window.findChild<QPlainTextEdit*>("commandDetails");
        auto* expand = window.findChild<QToolButton*>("commandDetailsToggle");
        check("bundled runner replaces missing saved runner", runner->text() == bundledWine);
        doctor->click();
        check("setup check locks conflicting controls immediately",
              !start->isEnabled() && !stop->isEnabled() && !doctor->isEnabled() && !runner->isEnabled());
        check("setup check failure completes asynchronously", waitFor([&] { return doctor->isEnabled(); }));
        check("setup diagnostic survives failure", details->toPlainText().contains("model fixture diagnostic") &&
              status->text().contains("exit 2"));
        check("bundled model fallback reaches CLI configuration",
              readFile(config).contains(("binaries=" + base + "/install/helper/binaries").toUtf8()));
        expand->click();
        check("diagnostics can be expanded", !details->isHidden());

        start->click();
        check("start locks controls while preparation runs", !start->isEnabled() && !doctor->isEnabled());
        pump(1100); // Let the status poll run before attempting the second click.
        check("status poll cannot unlock an in-flight start", !start->isEnabled());
        start->click();
        QMetaObject::invokeMethod(&window, "startHelper", Qt::DirectConnection);
        QMetaObject::invokeMethod(&window, "stopHelper", Qt::DirectConnection);
        check("failed start returns controls for retry", waitFor([&] { return start->isEnabled(); }));
        check("duplicate starts and concurrent stop are suppressed", readFile(calls) == "doctor\nstart\n");
        check("stdout and stderr survive a failed start", details->toPlainText().contains("preparing runtime") &&
              details->toPlainText().contains("download failed; try again") && status->text().contains("exit 17"));
        const QString failure = status->text();
        pump(1100);
        check("runtime status polling preserves command errors", status->text() == failure);

        if (const QString screenshot = qEnvironmentVariable("DLSSNR_TEST_SCREENSHOT"); !screenshot.isEmpty()) {
            window.show();
            pump(100);
            check("save GUI verification image", window.grab().save(screenshot));
        }

        writeFile(calls + ".retry", "");
        start->click();
        check("a subsequent start can succeed", waitFor([&] { return start->isEnabled(); }) &&
              status->text().startsWith("Start command completed."));
        check("CLI success does not claim model output", !window.findChild<QLabel*>("helperStatus")->text().contains("running") &&
              status->text().contains("Check Helper status"));
    }

    qputenv("DLSSNR_HELPER_CLI", (base + "/missing-helper").toUtf8());
    {
        MainWindow window;
        auto* start = window.findChild<QPushButton*>("startHelper");
        start->click();
        check("missing executable produces recoverable launch error", waitFor([&] { return start->isEnabled(); }) &&
              window.findChild<QLabel*>("commandStatus")->text().contains("Could not launch"));
        check("failed launch remains available in Details",
              window.findChild<QPlainTextEdit*>("commandDetails")->toPlainText().contains("Could not launch"));
    }

    qputenv("DLSSNR_SETUP_ERROR", "Conflicting Vulkan layer. Reopen after resolving the other installation.");
    {
        MainWindow window;
        check("package setup failures remain visible and block start",
              window.findChild<QLabel*>("setupIssue")->text().contains("Conflicting Vulkan layer") &&
              !window.findChild<QPushButton*>("startHelper")->isEnabled());
    }
    qunsetenv("DLSSNR_SETUP_ERROR");

    // A saved, executable runner wins over the bundled default.
    writeFile(config, "runner_type=wine\nrunner_path=/bin/true\n");
    qputenv("DLSSNR_HELPER_CLI", cli.toUtf8());
    {
        MainWindow window;
        check("valid saved runner is preserved", window.findChild<QLineEdit*>("runnerPath")->text() == "/bin/true");
        window.show();
        window.findChild<QPushButton*>("startHelper")->click();
        pump(100);
        window.close();
        check("closing waits for preparation before stopping", window.isVisible());
        check("window closes after ordered helper shutdown", waitFor([&] { return !window.isVisible(); }));
        check("close dispatches stop after start completes", readFile(calls).endsWith("start\nstop\n"));
    }

    // A previously extracted package must not pin a new GUI to the old model set.
    writeFile(base + "/old package/helper/binaries/nvngx_dlssnr.dll", "old bundled model");
    writeFile(base + "/old package/bundle-metadata.json", "{}");
    writeFile(config, ("runner_type=wine\nrunner_path=/bin/true\nbinaries=" +
                      base + "/old package/helper/binaries\n").toUtf8());
    {
        MainWindow window;
        auto* doctor = window.findChild<QPushButton*>("checkSetup");
        doctor->click();
        check("new package replaces saved old package model path", waitFor([&] { return doctor->isEnabled(); }) &&
              readFile(config).contains(("binaries=" + base + "/install/helper/binaries").toUtf8()));
        check("old package model is left intact",
              readFile(base + "/old package/helper/binaries/nvngx_dlssnr.dll") == "old bundled model");
    }

    // Model import into user data must take precedence over optional bundled files.
    writeFile(base + "/data/dlssnr/binaries/nvngx_dlssnr.dll", "user model");
    writeFile(config, "runner_type=wine\nrunner_path=/bin/true\n");
    {
        MainWindow window;
        auto* doctor = window.findChild<QPushButton*>("checkSetup");
        doctor->click();
        check("user model path remains preferred", waitFor([&] { return doctor->isEnabled(); }) &&
              readFile(config).contains(("binaries=" + base + "/data/dlssnr/binaries").toUtf8()));
    }

    // Keep this fixture next to only the test executable; never replace an existing CLI.
    const QString sibling = QCoreApplication::applicationDirPath() + "/dlssnr-helper";
    if (!QFile::exists(sibling)) {
        check("create sibling CLI fixture", writeFile(sibling, "#!/bin/sh\necho bundled-sibling\nexit 0\n", true));
        writeFile(base + "/path/dlssnr-helper", "#!/bin/sh\necho wrong-PATH-copy\nexit 0\n", true);
        qputenv("PATH", (base + "/path:/usr/bin:/bin").toUtf8());
        qunsetenv("DLSSNR_HELPER_CLI");
        {
            MainWindow window;
            auto* doctor = window.findChild<QPushButton*>("checkSetup");
            doctor->click();
            check("sibling CLI wins over PATH copy", waitFor([&] { return doctor->isEnabled(); }) &&
                  window.findChild<QPlainTextEdit*>("commandDetails")->toPlainText().contains("bundled-sibling"));
            qputenv("DLSSNR_HELPER_CLI", cli.toUtf8());
            doctor->click();
            check("explicit CLI override wins over sibling", waitFor([&] { return doctor->isEnabled(); }) &&
                  window.findChild<QPlainTextEdit*>("commandDetails")->toPlainText().contains("model fixture diagnostic"));
        }
        QFile::remove(sibling);
    } else {
        check("test directory must not contain an existing helper CLI", false);
    }
    return failures ? 1 : 0;
}
