/**
 * Chatbot d'aide Sacadoc
 * Système de chatbot basé sur un arbre de décision pour guider les utilisateurs
 */

class Chatbot {
    constructor() {
        this.tree = null;
        this.currentNode = 'start';
        this.videos = [];
        this.isOpen = false;
        
        this.container = document.getElementById('chatbot-container');
        this.toggleBtn = document.getElementById('chatbot-toggle');
        this.window = document.getElementById('chatbot-window');
        this.body = document.getElementById('chatbot-body');
        this.minimizeBtn = document.getElementById('chatbot-minimize');
        this.resetBtn = document.getElementById('chatbot-reset');
        
        this.init();
    }
    
    async init() {
        try {
            // Charger l'arbre de décision
            const response = await fetch('/static/data/chatbot_tree.json');
            this.tree = await response.json();
            
            // Récupérer les vidéos depuis l'API
            await this.loadVideos();
            
            // Événements
            this.toggleBtn.addEventListener('click', () => this.toggle());
            this.minimizeBtn.addEventListener('click', () => this.close());
            this.resetBtn.addEventListener('click', () => this.reset());
            
            // Démarrer la conversation
            this.displayNode(this.currentNode);
        } catch (error) {
            console.error('Erreur lors de l\'initialisation du chatbot:', error);
        }
    }
    
    async loadVideos() {
        try {
            // Essayer de charger depuis window.AIDE_VIDEOS d'abord
            if (window.AIDE_VIDEOS) {
                this.videos = window.AIDE_VIDEOS;
                console.log(`${this.videos.length} vidéos chargées depuis la page:`, this.videos);
            } else {
                // Sinon, charger depuis l'API
                const response = await fetch('/utilisateur/aide/api/videos/');
                if (response.ok) {
                    this.videos = await response.json();
                    console.log(`${this.videos.length} vidéos chargées depuis l'API:`, this.videos);
                } else {
                    console.warn('Impossible de charger les vidéos depuis l\'API');
                    this.videos = [];
                }
            }
        } catch (error) {
            console.error('Erreur lors du chargement des vidéos:', error);
            this.videos = [];
        }
    }
    
    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }
    
    open() {
        this.isOpen = true;
        this.window.classList.add('show');
        
        // Animation du bouton
        const icons = this.toggleBtn.querySelectorAll('.toggle-icon');
        icons[0].classList.add('hidden');
        icons[1].classList.remove('hidden');
    }
    
    close() {
        this.isOpen = false;
        this.window.classList.remove('show');
        
        // Animation du bouton
        const icons = this.toggleBtn.querySelectorAll('.toggle-icon');
        icons[0].classList.remove('hidden');
        icons[1].classList.add('hidden');
    }
    
    reset() {
        this.currentNode = 'start';
        this.body.innerHTML = '';
        this.displayNode(this.currentNode);
    }
    
    displayNode(nodeId, userChoice = null) {
        const node = this.tree[nodeId];
        if (!node) {
            console.error('Node non trouvé:', nodeId);
            return;
        }
        
        this.currentNode = nodeId;
        
        // Afficher le choix de l'utilisateur si présent
        if (userChoice) {
            this.addUserMessage(userChoice);
        }
        
        // Créer le message
        const messageDiv = document.createElement('div');
        messageDiv.className = 'chatbot-message';
        
        // Contenu du message
        const contentDiv = document.createElement('div');
        contentDiv.className = 'chatbot-message-content';
        contentDiv.textContent = node.content;
        messageDiv.appendChild(contentDiv);
        
        // Si c'est une vidéo, l'afficher
        if (node.type === 'video') {
            const videoIndex = node.video_index;
            
            if (this.videos.length === 0) {
                console.warn('Aucune vidéo disponible dans le chatbot');
            } else if (videoIndex !== undefined && videoIndex < this.videos.length) {
                const video = this.videos[videoIndex];
                const videoContainer = this.createVideoEmbed(video);
                messageDiv.appendChild(videoContainer);
            } else {
                console.warn(`Vidéo non trouvée à l'index ${videoIndex}. Total vidéos: ${this.videos.length}`);
            }
        }
        
        // Options/boutons
        if (node.options && node.options.length > 0) {
            const optionsDiv = document.createElement('div');
            optionsDiv.className = 'chatbot-options';
            
            node.options.forEach(option => {
                const btn = document.createElement('button');
                btn.className = 'chatbot-option-btn';
                btn.textContent = option.label;
                btn.addEventListener('click', () => {
                    // Masquer tous les boutons après le clic
                    optionsDiv.style.display = 'none';
                    // Ne plus effacer l'historique
                    this.displayNode(option.next, option.label);
                });
                optionsDiv.appendChild(btn);
            });
            
            messageDiv.appendChild(optionsDiv);
        }
        
        // Ajouter au corps du chatbot
        this.body.appendChild(messageDiv);
        
        // Scroll vers le bas
        this.body.scrollTop = this.body.scrollHeight;
    }
    
    addUserMessage(text) {
        const userMessageDiv = document.createElement('div');
        userMessageDiv.className = 'chatbot-user-message';
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'chatbot-user-message-content';
        contentDiv.textContent = text;
        
        userMessageDiv.appendChild(contentDiv);
        this.body.appendChild(userMessageDiv);
        
        // Scroll vers le bas
        this.body.scrollTop = this.body.scrollHeight;
    }
    
    createVideoEmbed(video) {
        if (!video || !video.video_id) {
            console.error('Vidéo invalide:', video);
            return document.createElement('div');
        }
        
        const container = document.createElement('div');
        container.className = 'chatbot-video-container';
        
        // Conteneur avec ratio 16:9
        const videoWrapper = document.createElement('div');
        videoWrapper.style.cssText = 'position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; border-radius: 6px; box-shadow: 0 0 4px rgba(0,0,0,0.1); margin-bottom: 8px;';
        
        // Iframe YouTube
        const iframe = document.createElement('iframe');
        iframe.src = `https://www.youtube-nocookie.com/embed/${video.video_id}?rel=0&enablejsapi=1`;
        iframe.style.cssText = 'position: absolute; top: 0; left: 0; width: 100%; height: 100%;';
        iframe.setAttribute('frameborder', '0');
        iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture');
        iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
        iframe.setAttribute('allowfullscreen', 'true');
        
        videoWrapper.appendChild(iframe);
        
        const title = document.createElement('div');
        title.className = 'chatbot-video-title';
        title.textContent = video.title || 'Vidéo sans titre';
        
        container.appendChild(videoWrapper);
        container.appendChild(title);
        
        return container;
    }
}

// Initialiser le chatbot quand le DOM est prêt
document.addEventListener('DOMContentLoaded', () => {
    new Chatbot();
});
