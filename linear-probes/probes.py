import torch.nn as nn

class LinearModel(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.linear = nn.Linear(input_dim, 1)

    def forward(self, x):
        return self.linear(x)

import torch as t
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

class LinearProbe:
    def __init__(self, input_dim, criterion=None, optimizer_cls=optim.Adam, lr=0.001, step_size=100, gamma=0.1, device='cpu'):
        self.device = device
        self.model = LinearModel(input_dim).to(self.device)
        self.criterion = criterion if criterion else nn.BCEWithLogitsLoss()
        self.optimizer = optimizer_cls(self.model.parameters(), lr=lr)
        self.lr_scheduler = optim.lr_scheduler.StepLR(self.optimizer, step_size=step_size, gamma=gamma)
        self.train_accs, self.test_accs = [], []

    def train_one_epoch(self, train_loader):
        self.model.train()
        total_loss, correct, total = 0, 0, 0
        
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(self.device, dtype=t.float32), y_batch.to(self.device, dtype=t.float32)
            
            y_pred = self.model(X_batch).squeeze()
            loss = self.criterion(y_pred, y_batch)
            
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
            
            total_loss += loss.item()
            correct += (y_pred.round() == y_batch).sum().item()
            total += y_batch.size(0)
        
        return total_loss / len(train_loader), correct / total
    
    def evaluate(self, test_loader):
        self.model.eval()
        total_loss, correct, total = 0, 0, 0
        
        with t.no_grad():
            for X_batch, y_batch in test_loader:
                X_batch, y_batch = X_batch.to(self.device, dtype=t.float32), y_batch.to(self.device, dtype=t.float32)
                
                y_pred = self.model(X_batch).squeeze()
                loss = self.criterion(y_pred, y_batch)
                
                total_loss += loss.item()
                correct += (y_pred.round() == y_batch).sum().item()
                total += y_batch.size(0)
        
        return total_loss / len(test_loader), correct / total
    
    def fit(self, train_loader: DataLoader, test_loader: DataLoader, epochs=1000):
        for epoch in range(epochs):
            train_loss, train_acc = self.train_one_epoch(train_loader)
            test_loss, test_acc = self.evaluate(test_loader)
            self.lr_scheduler.step()
            
            self.train_accs.append(train_acc)
            self.test_accs.append(test_acc)
            
            if (epoch + 1) % 100 == 0:
                print(f"Epoch {epoch+1}: Train Loss = {train_loss:.4f}, Train Acc = {train_acc:.4f}, "
                      f"Test Loss = {test_loss:.4f}, Test Acc = {test_acc:.4f}")
        
        print(f"Final Train Acc: {self.train_accs[-1]:.4f}, Final Test Acc: {self.test_accs[-1]:.4f}")