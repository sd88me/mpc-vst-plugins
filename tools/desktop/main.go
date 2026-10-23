// mpc-installer: a small local app that installs MPC OS plugins on a device over SSH.
//
// It starts a web page on this computer (127.0.0.1 only, behind a random token), opens it in the browser and does the work from
// there: connect to the device, pick plugins from the catalog or drop release zips, install. It uses the release zips' own
// install.sh, so there is still one install path (docs/RELEASING.md). Nothing about the device is stored on this computer.
package main

import (
	"crypto/rand"
	"encoding/hex"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"time"
)

// version is set by the release build (-ldflags "-X main.version=1.0.0").
var version = "dev"

func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	_ = cmd.Start()
}

func main() {
	port := flag.Int("port", 0, "port on 127.0.0.1 (0 = pick a free one)")
	noBrowser := flag.Bool("no-browser", false, "do not open the browser, just print the link")
	catalog := flag.String("catalog", defaultCatalogURL, "catalog.json address")
	noUpdateCheck := flag.Bool("no-update-check", false, "do not look for a newer installer release on GitHub")
	showVersion := flag.Bool("version", false, "print the version and exit")
	flag.Parse()
	if *showVersion {
		fmt.Println("mpc-installer", version)
		return
	}

	work, err := tempWorkDir()
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot create a work folder:", err)
		os.Exit(1)
	}
	defer os.RemoveAll(work)
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	token := hex.EncodeToString(b)
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", *port))
	if err != nil {
		fmt.Fprintln(os.Stderr, "cannot listen:", err)
		os.Exit(1)
	}
	app := NewApp(defaultConfig(), token, ln.Addr().String(), *catalog, work)
	if *noUpdateCheck {
		app.releasesURL = ""
	}
	link := fmt.Sprintf("http://%s/?t=%s", ln.Addr().String(), token)
	srv := &http.Server{Handler: app.Handler(), ReadHeaderTimeout: 10 * time.Second}
	fmt.Println("MPC plugin installer", version, "is running. Open this link in your browser (it only works on this computer):")
	fmt.Println()
	fmt.Println("  " + link)
	fmt.Println()
	fmt.Println("Press Ctrl+C here to quit.")
	if !*noBrowser {
		openBrowser(link)
	}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt)
	go func() { <-stop; srv.Close() }()
	if err := srv.Serve(ln); err != nil && err != http.ErrServerClosed {
		fmt.Fprintln(os.Stderr, err)
	}
}
