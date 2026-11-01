(() => {
  "use strict";
  const USER = "Adarsh-Singh-Chauhan";
  const PROFILE_REPO = USER + "/" + USER;
  const API = "https://api.github.com";
  const languageColors = {
    TypeScript:"#3178c6", JavaScript:"#f1e05a", Python:"#3572A5", Java:"#b07219",
    HTML:"#e34c26", CSS:"#563d7c", "C++":"#f34b7d", C:"#555555", "C#":"#178600",
    Go:"#00ADD8", Rust:"#dea584", PHP:"#4F5D95", Shell:"#89e051", Dart:"#00B4AB"
  };

  const stacks = {
    languages:[
      ["PY","Python","#3776ab"],["J","Java","#e76f00"],["JS","JavaScript","#e8cb38"],
      ["TS","TypeScript","#3178c6"],["C+","C++","#5686c6"],["C","C","#8b99ad"],
      ["#","C#","#9b75d7"]
    ],
    frontend:[
      ["R","React","#61dafb"],["N","Next.js","#dce7f7"],["HT","HTML5","#e34c26"],
      ["CS","CSS3","#4c83da"],["TW","Tailwind","#39b8d6"],["FM","Framer Motion","#a78bfa"]
    ],
    backend:[
      ["NO","Node.js","#65b86c"],["FA","FastAPI","#009688"],["FL","Flask","#e8eaf2"],
      ["RE","REST APIs","#49b8da"],["MY","MySQL","#4479a1"],["PG","PostgreSQL","#4169e1"],
      ["SB","Supabase","#3ecf8e"]
    ],
    ai:[
      ["ML","Machine Learning","#f472b6"],["AI","AI Applications","#b18af5"],
      ["RG","RAG","#22d3ee"],["OC","OCR","#fbbf24"],["GM","Gemini API","#8ab4f8"],
      ["AG","Agentic AI","#47e6a3"]
    ],
    cloud:[
      ["DO","Docker","#2496ed"],["AW","AWS","#f7a928"],["GI","Git","#f05032"],
      ["GH","GitHub","#f8fafc"],["VE","Vercel","#f8fafc"],["LX","Linux","#e4c34b"]
    ],
    tools:[
      ["VS","VS Code","#3b9ddd"],["FG","Figma","#f36e5b"],["PM","Postman","#ff6c37"],
      ["DB","DBeaver","#5d8ac7"],["AN","Antigravity","#b38cff"],["DC","Documentation","#9fb2ca"]
    ]
  };

  const el = (id) => document.getElementById(id);
  const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[ch]));
  const shortDate = (value) => {
    if (!value) return "recently";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "recently";
    return new Intl.DateTimeFormat(undefined,{day:"numeric",month:"short",year:"numeric"}).format(date);
  };
  const compact = (num) => new Intl.NumberFormat(undefined,{notation:"compact",maximumFractionDigits:1}).format(num || 0);

  async function api(path) {
    const response = await fetch(API + path, {
      headers: {"Accept":"application/vnd.github+json"},
      cache: "no-store"
    });
    if (!response.ok) {
      const error = new Error("GitHub API returned " + response.status);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  function setMetric(id, value) {
    const node = el(id);
    if (node) node.textContent = value;
  }

  function renderLanguages(languageTotals) {
    const bar = el("languageBar");
    const legend = el("languageLegend");
    if (!bar || !legend) return;
    const sorted = Object.entries(languageTotals).sort((a,b)=>b[1]-a[1]).slice(0,7);
    const total = sorted.reduce((sum,item)=>sum + item[1],0);
    if (!total || !sorted.length) {
      bar.innerHTML = '<span class="language-empty"></span>';
      legend.innerHTML = "<span>Language data is not available yet.</span>";
      return;
    }
    bar.innerHTML = sorted.map(([name,value]) =>
      '<span title="' + safe(name) + ' ' + (value/total*100).toFixed(1) + '%" style="width:' + (value/total*100).toFixed(2) + '%;background:' + (languageColors[name] || "#8b9bb4") + '"></span>'
    ).join("");
    legend.innerHTML = sorted.slice(0,5).map(([name,value]) =>
      '<span><i style="background:' + (languageColors[name] || "#8b9bb4") + '"></i>' + safe(name) + ' ' + (value/total*100).toFixed(1) + '%</span>'
    ).join("");
  }

  function renderRepositories(repos) {
    const latest = el("latestRepoList");
    const top = el("topRepoList");
    if (top) {
      const mostStarred = [...repos].sort((a,b)=>(b.stargazers_count||0)-(a.stargazers_count||0)).slice(0,5);
      top.innerHTML = mostStarred.length ? mostStarred.map((repo,index) => {
        const language = repo.language ? safe(repo.language) : "Project";
        return '<a class="top-repo-item" href="' + safe(repo.html_url) + '" target="_blank" rel="noreferrer">' +
          '<span class="repo-glyph">' + ["▤","◈","⌘","⬡","✦"][index] + '</span>' +
          '<strong title="' + safe(repo.name) + '">' + safe(repo.name) + '</strong>' +
          '<span class="repo-stars">★ ' + compact(repo.stargazers_count) + '</span>' +
          '<small>' + language + '</small></a>';
      }).join("") : '<div class="loading-line">No public repositories were returned.</div>';
    }
    if (latest) {
      latest.innerHTML = repos.slice(0,8).map(repo =>
        '<a class="repo-feed-row" href="' + safe(repo.html_url) + '" target="_blank" rel="noreferrer">' +
        '<span class="repo-feed-name">' + safe(repo.name) + '</span>' +
        '<span class="repo-feed-language">' + safe(repo.language || "—") + '</span>' +
        '<span class="repo-feed-stars">★ ' + compact(repo.stargazers_count) + '</span>' +
        '<span class="repo-feed-date">' + shortDate(repo.pushed_at || repo.updated_at) + '</span></a>'
      ).join("");
    }
  }

  function eventSummary(event) {
    const payload = event.payload || {};
    const repoName = event.repo?.name || "a public repository";
    const repoLink = "https://github.com/" + repoName;
    const kind = event.type;
    const messages = {
      PushEvent: "Pushed " + (payload.size || 1) + " commit(s) to",
      CreateEvent: "Created " + (payload.ref_type || "a ref") + " in",
      PullRequestEvent: (payload.action || "updated") + " a pull request in",
      IssuesEvent: (payload.action || "updated") + " an issue in",
      ReleaseEvent: "Published a release in",
      WatchEvent: "Starred",
      ForkEvent: "Forked"
    };
    const label = messages[kind] || kind.replace("Event"," event");
    return {label,repoName,repoLink,date:event.created_at};
  }

  function renderActivity(events) {
    const list = el("activityList");
    if (!list) return;
    const supported = events.filter(e => [
      "PushEvent","CreateEvent","PullRequestEvent","IssuesEvent","ReleaseEvent","WatchEvent","ForkEvent"
    ].includes(e.type)).slice(0,6);
    if (!supported.length) {
      list.innerHTML = '<div class="loading-line">No recent public events are available from GitHub right now.</div>';
      return;
    }
    const colors = ["#47e6a3","#32d9f5","#a78bfa","#ff3b9d","#ffd166","#5e9dff"];
    list.innerHTML = supported.map((event,index) => {
      const info = eventSummary(event);
      return '<div class="activity-item"><div class="activity-track"><i style="--event-color:' + colors[index % colors.length] + '"></i></div>' +
        '<div><strong>' + safe(info.label) + ' <a href="' + safe(info.repoLink) + '" target="_blank" rel="noreferrer">' + safe(info.repoName.split("/").pop()) + '</a></strong>' +
        '<small>' + shortDate(info.date) + ' · public activity</small></div></div>';
    }).join("");
  }

  async function refreshDashboard() {
    const status = el("lastUpdated");
    try {
      if (status) status.textContent = "Syncing public GitHub data…";
      const [user,repos,events] = await Promise.all([
        api("/users/" + USER),
        api("/users/" + USER + "/repos?type=owner&sort=pushed&per_page=100"),
        api("/users/" + USER + "/events/public?per_page=30").catch(() => [])
      ]);
      const publicRepos = repos.filter(repo => repo.private === false && !repo.fork && !repo.archived && repo.full_name !== PROFILE_REPO);
      const allPublic = repos.filter(repo => repo.private === false);
      const stars = allPublic.reduce((sum,repo)=>sum + (repo.stargazers_count || 0),0);
      const forks = allPublic.reduce((sum,repo)=>sum + (repo.forks_count || 0),0);
      setMetric("repoCount", compact(user.public_repos ?? publicRepos.length));
      setMetric("starCount", compact(stars));
      setMetric("forkCount", compact(forks));
      setMetric("followerCount", compact(user.followers || 0));

      renderRepositories(publicRepos);
      renderActivity(events);

      const languageTotals = {};
      const languageTargets = publicRepos.filter(repo=>repo.languages_url).slice(0,18);
      await Promise.all(languageTargets.map(async repo => {
        try {
          const languages = await api("/repos/" + USER + "/" + encodeURIComponent(repo.name) + "/languages");
          Object.entries(languages).forEach(([name,bytes])=>{
            languageTotals[name]=(languageTotals[name]||0)+bytes;
          });
        } catch (_) { /* one repository's language endpoint should not break the dashboard */ }
      }));
      renderLanguages(languageTotals);
      const date = new Intl.DateTimeFormat(undefined,{hour:"2-digit",minute:"2-digit",day:"numeric",month:"short"}).format(new Date());
      if (status) status.textContent = "SYNCED " + date + " · PUBLIC DATA";
      const languageStatus = el("languageStatus");
      if (languageStatus) languageStatus.textContent = languageTargets.length + " REPOSITORIES";
    } catch (error) {
      if (status) status.textContent = error.status === 403 ? "GITHUB API RATE LIMIT · TRY AGAIN LATER" : "LIVE DATA TEMPORARILY UNAVAILABLE";
      const list=el("activityList");
      if(list) list.innerHTML='<div class="loading-line">GitHub API could not be reached. The rest of the portfolio remains available.</div>';
      const top=el("topRepoList");
      if(top) top.innerHTML='<div class="loading-line">Public repository data is temporarily unavailable.</div>';
    }
  }

  function renderStack(tab) {
    const root = el("stackGrid");
    if (!root) return;
    const items = stacks[tab] || stacks.languages;
    root.innerHTML = items.map(([glyph,name,color]) =>
      '<div class="skill-tile" style="--skill-color:' + color + '"><span class="skill-glyph">' + safe(glyph) + '</span><span>' + safe(name) + '</span></div>'
    ).join("");
  }

  function initStackTabs() {
    const buttons = document.querySelectorAll(".stack-tab");
    buttons.forEach(button => button.addEventListener("click",()=>{
      buttons.forEach(other=>other.classList.toggle("active",other===button));
      renderStack(button.dataset.stack);
    }));
    renderStack("languages");
  }

  function initNavigation() {
    const toggle=el("menuToggle"),nav=el("mainNav");
    if(toggle && nav){
      toggle.addEventListener("click",()=>{
        const open=nav.classList.toggle("open");
        toggle.setAttribute("aria-expanded",String(open));
      });
      nav.querySelectorAll("a").forEach(link=>link.addEventListener("click",()=>{
        nav.classList.remove("open");
        toggle.setAttribute("aria-expanded","false");
      }));
    }
    document.querySelectorAll('.main-nav a').forEach(link=>{
      link.addEventListener("click",()=>{
        document.querySelectorAll('.main-nav a').forEach(a=>a.classList.toggle("active",a===link));
      });
    });
  }

  function initReveal() {
    const nodes=document.querySelectorAll(".reveal");
    if(!("IntersectionObserver" in window)){nodes.forEach(node=>node.classList.add("is-visible"));return;}
    const observer=new IntersectionObserver(entries=>{
      entries.forEach(entry=>{
        if(entry.isIntersecting){entry.target.classList.add("is-visible");observer.unobserve(entry.target);}
      });
    },{threshold:.08});
    nodes.forEach(node=>observer.observe(node));
  }

  function initTerminal() {
    const node=el("terminalText");
    if(!node)return;
    const commands=[
      "building_real_world_software()",
      "designing_scalable_systems()",
      "exploring_agentic_ai()",
      "vibe_coding_with_engineering()",
      "testing_before_shipping()"
    ];
    let index=0;
    window.setInterval(()=>{
      index=(index+1)%commands.length;
      node.textContent=commands[index];
    },2600);
  }

  document.addEventListener("DOMContentLoaded",()=>{
    const year=el("year");if(year)year.textContent=String(new Date().getFullYear());
    initNavigation();
    initReveal();
    initStackTabs();
    initTerminal();
    refreshDashboard();
  });
})();